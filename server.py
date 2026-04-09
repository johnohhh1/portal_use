#!/usr/bin/env python3
"""
portal-use: Wayland-native computer use MCP server.

Uses XDG Desktop Portal (RemoteDesktop + ScreenCast) + PipeWire + libei.
No X11. No root. No kernel hacks.

The portal consent dialog fires ONCE when this server starts, then the session
is kept alive for all subsequent tool calls — no prompts per tool use.

Usage:
  claude mcp add --scope user portal-use -- \
    /home/johnohhh1/portal_use/.venv/bin/python /home/johnohhh1/portal_use/server.py
"""

import asyncio
import sys
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from portal.session import PortalSession
from portal.capture import ScreenCapture, scale_image_for_api, image_to_png_b64
from portal.input import EIInput, BTN_LEFT, BTN_RIGHT, BTN_MIDDLE


app = Server("portal-use")

# ── Session state (module-level, shared across all tool calls) ─────────────────
_session: Optional[PortalSession] = None
_capture: Optional[ScreenCapture] = None
_input:   Optional[EIInput]       = None
_scale_factor: float = 1.0
_phys_width:   int   = 0
_phys_height:  int   = 0
_session_lock = asyncio.Lock()


async def _init_session():
    """
    Establish the portal session and start capture + input.
    Called once at server startup — this is where the consent dialog appears.
    Auto-called again if the session is lost.
    """
    global _session, _capture, _input, _scale_factor, _phys_width, _phys_height

    print("[portal-use] Starting portal session...", file=sys.stderr, flush=True)
    print("[portal-use] A consent dialog may appear on your desktop — approve it once.",
          file=sys.stderr, flush=True)

    _session = PortalSession()
    await _session.start()

    if not _session.streams:
        raise RuntimeError("Portal returned no streams")

    node_id, stream_props = _session.streams[0]
    if "size" in stream_props:
        _phys_width, _phys_height = stream_props["size"].value
    else:
        _phys_width, _phys_height = 1920, 1080

    # Start PipeWire capture
    if _capture:
        _capture.stop()
    _capture = ScreenCapture(pw_fd=_session.pw_fd, node_id=node_id)
    _capture.start()

    # Grab one frame to get actual dimensions
    frame = await asyncio.get_running_loop().run_in_executor(
        None, lambda: _capture.grab_frame(timeout=10.0)
    )
    if frame:
        _phys_width, _phys_height = frame.size

    # Calculate scale factor (max 1568px long edge for API)
    long_edge = max(_phys_width, _phys_height)
    _scale_factor = min(1.0, 1568 / long_edge)

    # Start libei input — connect() must run in the main thread (not executor)
    # because ei_seat_bind_capabilities is a varargs C function and ctypes
    # varargs dispatch from a thread pool segfaults on x86-64 due to stack
    # alignment. Short blocking call (<1s) is acceptable at startup.
    if _input:
        _input.close()
    _input = EIInput(
        ei_fd=_session.ei_fd,
        screen_width=_phys_width,
        screen_height=_phys_height,
    )
    _input.connect()

    print(
        f"[portal-use] Ready. {_phys_width}x{_phys_height}, "
        f"scale={_scale_factor:.3f}, session={_session.session_path}",
        file=sys.stderr, flush=True,
    )


async def ensure_session():
    """
    Ensure the portal session is active. Reconnects automatically if dropped.
    Each tool call goes through here — normally a no-op after first init.
    """
    global _session
    async with _session_lock:
        needs_init = (
            _session is None
            or not _session.is_alive()
            or _capture is None
            or _input is None
        )
        if needs_init:
            if _session is not None and not _session.is_alive():
                print("[portal-use] Session appears dead, reinitializing...", file=sys.stderr, flush=True)
            await _init_session()


def logical_to_physical(x: float, y: float) -> tuple[float, float]:
    if _scale_factor == 1.0:
        return x, y
    return x / _scale_factor, y / _scale_factor


# ── Tool definitions ───────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="computer_screenshot",
            description="Take a screenshot of the Wayland desktop. Returns a base64 PNG.",
            inputSchema={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "object",
                        "description": "Optional crop region in logical coordinates",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "width": {"type": "number"}, "height": {"type": "number"},
                        },
                    }
                },
            },
        ),
        types.Tool(
            name="computer_click",
            description="Click at the specified coordinates.",
            inputSchema={
                "type": "object",
                "required": ["x", "y"],
                "properties": {
                    "x": {"type": "number", "description": "Logical X coordinate"},
                    "y": {"type": "number", "description": "Logical Y coordinate"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "double": {"type": "boolean", "description": "Double-click", "default": False},
                },
            },
        ),
        types.Tool(
            name="computer_move",
            description="Move the mouse cursor to coordinates without clicking.",
            inputSchema={
                "type": "object", "required": ["x", "y"],
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
            },
        ),
        types.Tool(
            name="computer_type",
            description="Type a text string into the currently focused window.",
            inputSchema={
                "type": "object", "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
        ),
        types.Tool(
            name="computer_key",
            description="Press a key or combination. Examples: 'enter', 'ctrl+c', 'alt+tab'.",
            inputSchema={
                "type": "object", "required": ["keys"],
                "properties": {"keys": {"type": "string"}},
            },
        ),
        types.Tool(
            name="computer_scroll",
            description="Scroll at the specified position.",
            inputSchema={
                "type": "object", "required": ["x", "y", "direction"],
                "properties": {
                    "x": {"type": "number"}, "y": {"type": "number"},
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "amount": {"type": "number", "default": 3},
                },
            },
        ),
        types.Tool(
            name="computer_drag",
            description="Click and drag from one position to another.",
            inputSchema={
                "type": "object", "required": ["start_x", "start_y", "end_x", "end_y"],
                "properties": {
                    "start_x": {"type": "number"}, "start_y": {"type": "number"},
                    "end_x": {"type": "number"}, "end_y": {"type": "number"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                },
            },
        ),
        types.Tool(
            name="computer_display_info",
            description="Get display resolution and coordinate space information.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="computer_zoom",
            description="Capture a region at full resolution for reading small text.",
            inputSchema={
                "type": "object", "required": ["x", "y", "width", "height"],
                "properties": {
                    "x": {"type": "number"}, "y": {"type": "number"},
                    "width": {"type": "number"}, "height": {"type": "number"},
                },
            },
        ),
        types.Tool(
            name="computer_health",
            description="Check the health of the portal session, screen capture, and input subsystems.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="computer_reset_session",
            description="Tear down and reinitialize the portal session. Consent dialog may reappear.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ── Tool handlers ─────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
    # Health and reset don't need a live session to be called
    if name == "computer_health":
        return await _tool_health()
    if name == "computer_reset_session":
        return await _tool_reset_session()

    await ensure_session()

    handlers = {
        "computer_screenshot":   lambda: _tool_screenshot(arguments),
        "computer_click":        lambda: _tool_click(arguments),
        "computer_move":         lambda: _tool_move(arguments),
        "computer_type":         lambda: _tool_type(arguments),
        "computer_key":          lambda: _tool_key(arguments),
        "computer_scroll":       lambda: _tool_scroll(arguments),
        "computer_drag":         lambda: _tool_drag(arguments),
        "computer_display_info": lambda: _tool_display_info(),
        "computer_zoom":         lambda: _tool_zoom(arguments),
    }
    if name not in handlers:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    return await handlers[name]()


async def _grab_frame():
    return await asyncio.get_running_loop().run_in_executor(
        None, lambda: _capture.grab_frame(timeout=5.0)
    )


async def _tool_screenshot(args: dict) -> list[types.ContentBlock]:
    frame = await _grab_frame()
    if frame is None:
        return [types.TextContent(type="text", text="Screenshot failed: no frame")]

    region = args.get("region")
    if region:
        px, py = logical_to_physical(region["x"], region["y"])
        pw, ph = region["width"] / _scale_factor, region["height"] / _scale_factor
        frame = frame.crop((int(px), int(py), int(px + pw), int(py + ph)))

    scaled, _ = scale_image_for_api(frame)
    return [types.ImageContent(type="image", data=image_to_png_b64(scaled), mimeType="image/png")]


async def _tool_click(args: dict) -> list[types.ContentBlock]:
    px, py = logical_to_physical(args["x"], args["y"])
    button = args.get("button", "left")
    double = args.get("double", False)
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: _input.click(px, py, button=button, double=double)
    )
    return [types.TextContent(type="text", text=f"Clicked {button} at ({args['x']}, {args['y']})")]


async def _tool_move(args: dict) -> list[types.ContentBlock]:
    px, py = logical_to_physical(args["x"], args["y"])
    await asyncio.get_running_loop().run_in_executor(None, lambda: _input.move(px, py))
    return [types.TextContent(type="text", text=f"Moved to ({args['x']}, {args['y']})")]


async def _tool_type(args: dict) -> list[types.ContentBlock]:
    text = args["text"]
    await asyncio.get_running_loop().run_in_executor(None, lambda: _input.type_text(text))
    return [types.TextContent(type="text", text=f"Typed {len(text)} characters")]


async def _tool_key(args: dict) -> list[types.ContentBlock]:
    keys = args["keys"]
    await asyncio.get_running_loop().run_in_executor(None, lambda: _input.key_combo(keys))
    return [types.TextContent(type="text", text=f"Pressed: {keys}")]


async def _tool_scroll(args: dict) -> list[types.ContentBlock]:
    px, py = logical_to_physical(args["x"], args["y"])
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: _input.scroll(px, py, args["direction"], args.get("amount", 3))
    )
    return [types.TextContent(type="text", text=f"Scrolled {args['direction']}")]


async def _tool_drag(args: dict) -> list[types.ContentBlock]:
    import time
    sx, sy = logical_to_physical(args["start_x"], args["start_y"])
    ex, ey = logical_to_physical(args["end_x"], args["end_y"])
    btn = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}.get(
        args.get("button", "left"), BTN_LEFT
    )

    def do_drag():
        _input.move(sx, sy)
        _input.button(btn, True)
        time.sleep(0.05)
        steps = 10
        for i in range(1, steps + 1):
            _input.move(sx + (ex - sx) * i / steps, sy + (ey - sy) * i / steps)
            time.sleep(0.02)
        _input.button(btn, False)

    await asyncio.get_running_loop().run_in_executor(None, do_drag)
    return [types.TextContent(type="text", text=f"Dragged ({args['start_x']},{args['start_y']}) → ({args['end_x']},{args['end_y']})")]


async def _tool_display_info() -> list[types.ContentBlock]:
    lw = int(_phys_width * _scale_factor)
    lh = int(_phys_height * _scale_factor)
    info = (
        f"Physical: {_phys_width}x{_phys_height}\n"
        f"Logical (agent space): {lw}x{lh}\n"
        f"Scale factor: {_scale_factor:.3f}"
    )
    return [types.TextContent(type="text", text=info)]


async def _tool_zoom(args: dict) -> list[types.ContentBlock]:
    frame = await _grab_frame()
    if frame is None:
        return [types.TextContent(type="text", text="Zoom failed: no frame")]
    px, py = logical_to_physical(args["x"], args["y"])
    pw, ph = args["width"] / _scale_factor, args["height"] / _scale_factor
    cropped = frame.crop((int(px), int(py), int(px + pw), int(py + ph)))
    return [types.ImageContent(type="image", data=image_to_png_b64(cropped), mimeType="image/png")]


async def _tool_health() -> list[types.ContentBlock]:
    parts = []
    if _session is None:
        parts.append("session: not initialized")
    elif _session.is_alive():
        parts.append(f"session: ok ({_session.session_path})")
    else:
        parts.append("session: dead (D-Bus disconnected)")

    if _capture is None:
        parts.append("capture: not initialized")
    else:
        # Try a quick frame grab to verify capture is live
        frame = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _capture.grab_frame(timeout=2.0)
        )
        if frame:
            parts.append(f"capture: ok ({frame.size[0]}x{frame.size[1]})")
        else:
            parts.append("capture: no frame (pipeline may be stalled)")

    if _input is None:
        parts.append("input: not initialized")
    elif _input._ei is not None:
        parts.append("input: ok")
    else:
        parts.append("input: disconnected")

    return [types.TextContent(type="text", text="\n".join(parts))]


async def _tool_reset_session() -> list[types.ContentBlock]:
    global _session, _capture, _input
    async with _session_lock:
        print("[portal-use] Resetting session...", file=sys.stderr, flush=True)
        if _capture:
            _capture.stop()
            _capture = None
        if _input:
            _input.close()
            _input = None
        if _session:
            await _session.close()
            _session = None
        try:
            await _init_session()
            return [types.TextContent(type="text", text="Session reset successful.")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Session reset failed: {e}")]


# ── Entry point ────────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
