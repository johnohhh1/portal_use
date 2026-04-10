"""
XDG Desktop Portal session manager.

Handles the full portal session lifecycle:
  CreateSession → SelectDevices → SelectSources → Start
  → ConnectToEIS (libei fd) → OpenPipeWireRemote (pw fd)

Uses dbus-next (asyncio) for all D-Bus communication.
"""

import asyncio
import os
import random
import string
import sys
from pathlib import Path
from typing import Optional

from dbus_next.aio import MessageBus
from dbus_next import BusType, Variant, Message, MessageType


PORTAL_BUS   = "org.freedesktop.portal.Desktop"
PORTAL_PATH  = "/org/freedesktop/portal/desktop"
REMOTE_IFACE = "org.freedesktop.portal.RemoteDesktop"
CAST_IFACE   = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"

# Persist token file — avoids re-prompting on restart
TOKEN_FILE = Path.home() / ".config" / "portal-use" / "session_token"


def _random_token(n=8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


class PortalSession:
    """
    Manages a joint RemoteDesktop + ScreenCast portal session.

    After start(), provides:
      self.ei_fd   — file descriptor for libei sender context
      self.pw_fd   — file descriptor for PipeWire remote
      self.streams — list of PipeWire stream dicts from portal
    """

    def __init__(self):
        self.bus: Optional[MessageBus] = None
        self.session_path: Optional[str] = None
        self.ei_fd: Optional[int] = None
        self.pw_fd: Optional[int] = None
        self.streams: list = []
        self._sender_token = _random_token()
        self._desktop_proxy = None
        self._restore_token: Optional[str] = None

    async def start(self):
        """Run the full portal session setup flow."""
        self.bus = await MessageBus(bus_type=BusType.SESSION, negotiate_unix_fd=True).connect()

        # Load persisted restore token — used to skip consent dialog on restart
        if TOKEN_FILE.exists():
            self._restore_token = TOKEN_FILE.read_text().strip() or None

        await self._create_session()
        # GNOME portal requires: SelectSources → SelectDevices → Start
        await self._select_sources()
        await self._select_devices()
        streams, restore_token = await self._start_session()
        self.streams = streams

        # Persist the restore token so future restarts skip the consent dialog
        if restore_token:
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(restore_token)
            print(f"[portal] Saved restore token for future restarts", file=sys.stderr, flush=True)

        await self._connect_to_eis()
        await self._open_pipewire_remote()

    async def _call_portal(self, iface: str, method: str, *args, timeout: float = 30.0) -> dict:
        """
        Make a portal method call and wait for its Response signal.

        Portal methods return a Request object path, not the result directly.
        The result arrives as a Response signal on that Request object.
        """
        handle_token = "portal_use_" + _random_token()
        sender_name = self.bus.unique_name.lstrip(":").replace(".", "_")

        request_path = f"/org/freedesktop/portal/desktop/request/{sender_name}/{handle_token}"

        result_future: asyncio.Future = asyncio.get_running_loop().create_future()

        def on_response(msg: Message):
            if (msg.message_type == MessageType.SIGNAL
                    and msg.path == request_path
                    and msg.member == "Response"):
                response_code = msg.body[0]
                results = msg.body[1]
                if not result_future.done():
                    if response_code == 0:
                        result_future.set_result(results)
                    else:
                        result_future.set_exception(
                            RuntimeError(f"Portal call {method} failed with code {response_code}")
                        )

        self.bus.add_message_handler(on_response)

        # Inject handle_token into the options dict (last arg must be dict)
        args = list(args)
        if args and isinstance(args[-1], dict):
            args[-1]["handle_token"] = Variant("s", handle_token)
        else:
            args.append({"handle_token": Variant("s", handle_token)})

        await self.bus.call(Message(
            destination=PORTAL_BUS,
            path=PORTAL_PATH,
            interface=iface,
            member=method,
            signature="".join(_dbus_sig(a) for a in args),
            body=args,
        ))

        try:
            result = await asyncio.wait_for(result_future, timeout=timeout)
        finally:
            self.bus.remove_message_handler(on_response)

        return result

    async def _create_session(self):
        session_token = "portal_use_session_" + _random_token()
        result = await self._call_portal(
            REMOTE_IFACE, "CreateSession",
            {"session_handle_token": Variant("s", session_token)},
        )
        self.session_path = result["session_handle"].value
        print(f"[portal] Session created: {self.session_path}", file=sys.stderr, flush=True)

    async def _select_devices(self):
        # KEYBOARD = 1, POINTER = 2
        options: dict = {"types": Variant("u", 3)}
        await self._call_portal(REMOTE_IFACE, "SelectDevices",
                                self.session_path, options, timeout=120.0)
        print("[portal] Devices selected (keyboard + pointer)", file=sys.stderr, flush=True)

    async def _select_sources(self):
        # persist_mode=1 → token valid until compositor session ends (login/logout).
        # persist_mode=2 → token survives reboots (preferred, but deadlocks on
        #                   xdg-desktop-portal-gnome 46–50 in combined RD+SC sessions).
        # We try mode=1 first; it avoids the deadlock and still means the consent
        # dialog fires only once per login session, not once per MCP server restart.
        options: dict = {
            "types": Variant("u", 1),
            "cursor_mode": Variant("u", 2),
            "persist_mode": Variant("u", 1),
        }
        if self._restore_token:
            options["restore_token"] = Variant("s", self._restore_token)
            print("[portal] Trying restore token (persist_mode=1 — valid until logout)", file=sys.stderr, flush=True)
        else:
            print("[portal] No restore token — consent dialog will appear once this login session", file=sys.stderr, flush=True)
        try:
            await self._call_portal(CAST_IFACE, "SelectSources", self.session_path, options, timeout=15.0)
        except asyncio.TimeoutError:
            # persist_mode deadlock — fall back to no persistence
            print("[portal] persist_mode timed out (known GNOME bug) — retrying without persistence", file=sys.stderr, flush=True)
            options.pop("persist_mode")
            options.pop("restore_token", None)
            await self._call_portal(CAST_IFACE, "SelectSources", self.session_path, options)
        print("[portal] Sources selected (monitor)", file=sys.stderr, flush=True)

    async def _start_session(self) -> tuple[list, Optional[str]]:
        # Start may show a one-time consent dialog — use 60s timeout
        result = await self._call_portal(
            REMOTE_IFACE, "Start",
            self.session_path, "",  # parent window handle (empty = no parent)
            {},
            timeout=60.0,
        )
        streams = result.get("streams", Variant("a(ua{sv})", [])).value
        restore_token = None
        if "restore_token" in result:
            restore_token = result["restore_token"].value

        if self._restore_token and restore_token:
            print(f"[portal] Session restored (no consent needed)", file=sys.stderr, flush=True)
        elif restore_token:
            print(f"[portal] First-time consent approved. Token saved.", file=sys.stderr, flush=True)
        else:
            print(f"[portal] Session started (no restore token from portal)", file=sys.stderr, flush=True)

        print(f"[portal] Started. {len(streams)} stream(s). Token: {restore_token}", file=sys.stderr, flush=True)
        return streams, restore_token

    async def _connect_to_eis(self):
        """Get the EIS file descriptor for libei input injection."""
        reply = await self.bus.call(Message(
            destination=PORTAL_BUS,
            path=PORTAL_PATH,
            interface=REMOTE_IFACE,
            member="ConnectToEIS",
            signature="oa{sv}",
            body=[self.session_path, {}],
        ))
        # Reply body[0] is UnixFd
        self.ei_fd = reply.unix_fds[0] if reply.unix_fds else reply.body[0]
        print(f"[portal] EIS fd: {self.ei_fd}", file=sys.stderr, flush=True)

    async def _open_pipewire_remote(self):
        """Get the PipeWire remote file descriptor for screen capture."""
        reply = await self.bus.call(Message(
            destination=PORTAL_BUS,
            path=PORTAL_PATH,
            interface=CAST_IFACE,
            member="OpenPipeWireRemote",
            signature="oa{sv}",
            body=[self.session_path, {}],
        ))
        self.pw_fd = reply.unix_fds[0] if reply.unix_fds else reply.body[0]
        print(f"[portal] PipeWire fd: {self.pw_fd}", file=sys.stderr, flush=True)

    def is_alive(self) -> bool:
        """Return True if the D-Bus session appears still valid."""
        return self.bus is not None and self.session_path is not None

    async def close(self):
        if self.bus and self.session_path:
            try:
                await self.bus.call(Message(
                    destination=PORTAL_BUS,
                    path=self.session_path,
                    interface="org.freedesktop.portal.Session",
                    member="Close",
                    signature="",
                    body=[],
                ))
            except Exception:
                pass
        if self.bus:
            self.bus.disconnect()
        # Null out all fields so is_alive() returns False after close
        self.bus = None
        self.session_path = None
        self.ei_fd = None
        self.pw_fd = None


def _dbus_sig(val) -> str:
    """Best-effort D-Bus signature inference for simple values."""
    if isinstance(val, Variant):
        return "v"
    if isinstance(val, str):
        # D-Bus object paths start with '/' — distinguish from plain strings
        return "o" if val.startswith("/") else "s"
    if isinstance(val, int):
        return "u"
    if isinstance(val, dict):
        return "a{sv}"
    if isinstance(val, list):
        return "av"
    return "v"
