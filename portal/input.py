"""
Wayland input injection via libei (Emulated Input) — sender context.

Correct libei sender flow:
  1. ei_new_sender() + ei_setup_backend_fd(ei, eis_fd)
  2. EI_EVENT_CONNECT → ei_configure_name(ei, name)
  3. EI_EVENT_SEAT_ADDED → ei_seat_bind_capabilities(seat, caps..., NULL)
  4. EI_EVENT_DEVICE_ADDED  × N  (server creates devices for us)
  5. EI_EVENT_DEVICE_RESUMED × N (devices ready)
  6. ei_device_start_emulating(device, seq)
  7. Send events + ei_device_frame(device, us) + ei_flush(ei)

Reference: libei 1.5.0 — https://libinput.pages.freedesktop.org/libei/
"""

import ctypes
import ctypes.util
import os
import select
import sys
import time

# Load libei
_libei_path = ctypes.util.find_library("ei") or "libei.so.1"
_libei = ctypes.CDLL(_libei_path)

# ── Types ─────────────────────────────────────────────────────────────────────
c_ei_p      = ctypes.c_void_p
c_seat_p    = ctypes.c_void_p
c_device_p  = ctypes.c_void_p
c_event_p   = ctypes.c_void_p

# ── Capability constants (enum ei_device_capability) — bit flags ─────────────
EI_DEVICE_CAP_POINTER          = 1   # 1 << 0
EI_DEVICE_CAP_POINTER_ABSOLUTE = 2   # 1 << 1
EI_DEVICE_CAP_KEYBOARD         = 4   # 1 << 2
EI_DEVICE_CAP_TOUCH            = 8   # 1 << 3
EI_DEVICE_CAP_SCROLL           = 16  # 1 << 4
EI_DEVICE_CAP_BUTTON           = 32  # 1 << 5

# ── Event types ───────────────────────────────────────────────────────────────
# Values from libei.h (libei 1.5.0)
EI_EVENT_CONNECT               = 1
EI_EVENT_DISCONNECT            = 2
EI_EVENT_SEAT_ADDED            = 3
EI_EVENT_SEAT_REMOVED          = 4
EI_EVENT_DEVICE_ADDED          = 5
EI_EVENT_DEVICE_REMOVED        = 6
EI_EVENT_DEVICE_PAUSED         = 7
EI_EVENT_DEVICE_RESUMED        = 8
EI_EVENT_KEYBOARD_MODIFIERS    = 9
EI_EVENT_PONG                  = 90
EI_EVENT_SYNC                  = 91
EI_EVENT_FRAME                 = 100
EI_EVENT_DEVICE_START_EMULATING = 200
EI_EVENT_DEVICE_STOP_EMULATING  = 201

# ── Function prototypes ───────────────────────────────────────────────────────
c_region_p  = ctypes.c_void_p

def _proto(name, argtypes, restype):
    fn = getattr(_libei, name, None)
    if fn is None:
        return
    fn.argtypes = argtypes
    fn.restype = restype

_proto("ei_new_sender",                  [ctypes.c_void_p],              c_ei_p)
_proto("ei_configure_name",             [c_ei_p, ctypes.c_char_p],      None)
_proto("ei_setup_backend_fd",           [c_ei_p, ctypes.c_int],         ctypes.c_int)
_proto("ei_get_fd",                     [c_ei_p],                       ctypes.c_int)
_proto("ei_dispatch",                   [c_ei_p],                       ctypes.c_int)
_proto("ei_get_event",                  [c_ei_p],                       c_event_p)
_proto("ei_event_unref",                [c_event_p],                    None)
_proto("ei_event_get_type",             [c_event_p],                    ctypes.c_int)
_proto("ei_event_get_seat",             [c_event_p],                    c_seat_p)
_proto("ei_event_get_device",           [c_event_p],                    c_device_p)
# ei_seat_bind_capabilities is varargs — call without argtypes restriction
_proto("ei_seat_has_capability",        [c_seat_p, ctypes.c_int],       ctypes.c_bool)
_proto("ei_seat_ref",                   [c_seat_p],                     c_seat_p)
_proto("ei_seat_unref",                 [c_seat_p],                     c_seat_p)
_proto("ei_device_start_emulating",     [c_device_p, ctypes.c_uint32],  None)
_proto("ei_device_stop_emulating",      [c_device_p],                   None)
_proto("ei_device_ref",                 [c_device_p],                   c_device_p)
_proto("ei_device_unref",               [c_device_p],                   c_device_p)
_proto("ei_device_has_capability",      [c_device_p, ctypes.c_int],     ctypes.c_bool)
_proto("ei_device_get_type",            [c_device_p],                   ctypes.c_int)
_proto("ei_device_get_region",          [c_device_p, ctypes.c_size_t],  c_region_p)
_proto("ei_region_get_x",               [c_region_p],                   ctypes.c_uint32)
_proto("ei_region_get_y",               [c_region_p],                   ctypes.c_uint32)
_proto("ei_region_get_width",           [c_region_p],                   ctypes.c_uint32)
_proto("ei_region_get_height",          [c_region_p],                   ctypes.c_uint32)
_proto("ei_device_pointer_motion_absolute", [c_device_p, ctypes.c_double, ctypes.c_double], None)
_proto("ei_device_pointer_motion",      [c_device_p, ctypes.c_double, ctypes.c_double], None)
_proto("ei_device_button_button",       [c_device_p, ctypes.c_uint32, ctypes.c_bool], None)
_proto("ei_device_scroll_delta",        [c_device_p, ctypes.c_double, ctypes.c_double], None)
_proto("ei_device_scroll_discrete",     [c_device_p, ctypes.c_double, ctypes.c_double], None)
_proto("ei_device_keyboard_key",        [c_device_p, ctypes.c_uint32, ctypes.c_bool], None)
_proto("ei_device_frame",               [c_device_p, ctypes.c_uint64],  None)
_proto("ei_flush",                      [c_ei_p],                       None)
_proto("ei_disconnect",                 [c_ei_p],                       None)
_proto("ei_unref",                      [c_ei_p],                       None)

# ── Input codes ───────────────────────────────────────────────────────────────
BTN_LEFT   = 0x110
BTN_RIGHT  = 0x111
BTN_MIDDLE = 0x112

KEY_CODES: dict[str, int] = {
    # Control keys
    "enter": 28, "return": 28, "tab": 15, "space": 57,
    "backspace": 14, "delete": 111, "escape": 1, "esc": 1,
    "ctrl": 29, "control": 29, "lctrl": 29, "rctrl": 97,
    "shift": 42, "lshift": 42, "rshift": 54,
    "alt": 56, "lalt": 56, "ralt": 100, "altgr": 100,
    "super": 125, "meta": 125, "win": 125,
    "capslock": 58, "numlock": 69, "scrolllock": 70,
    "printscreen": 99, "pause": 119,
    # Navigation
    "up": 103, "down": 108, "left": 105, "right": 106,
    "home": 102, "end": 107, "pageup": 104, "pagedown": 109,
    "insert": 110,
    # Function keys
    "f1": 59, "f2": 60, "f3": 61, "f4": 62,
    "f5": 63, "f6": 64, "f7": 65, "f8": 66,
    "f9": 67, "f10": 68, "f11": 87, "f12": 88,
    # Space character (also accessible via "space" key name above)
    " ": 57,
    # Punctuation / symbols (unshifted)
    "`": 41, "-": 12, "=": 13,
    "[": 26, "]": 27, "\\": 43,
    ";": 39, "'": 40,
    ",": 51, ".": 52, "/": 53,
    # Numpad
    "kp0": 82, "kp1": 79, "kp2": 80, "kp3": 81,
    "kp4": 75, "kp5": 76, "kp6": 77,
    "kp7": 71, "kp8": 72, "kp9": 73,
    "kpenter": 96, "kp+": 78, "kp-": 74, "kp*": 55, "kp/": 98, "kp.": 83,
}

# Shifted symbol aliases — these map to the same keycode as the base key
# type_text uses these to know shift is needed
_SHIFT_MAP: dict[str, str] = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4",
    "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "-", "+": "=",
    "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'",
    "<": ",", ">": ".", "?": "/",
}

# Alpha keys
_alpha_codes = [30,48,46,32,18,33,34,35,23,36,37,38,50,49,24,25,16,19,31,20,22,47,17,45,21,44]
for _i, _ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEY_CODES[_ch] = _alpha_codes[_i]
# Digit keys
for _i in range(10):
    KEY_CODES[str(_i)] = 11 if _i == 0 else (_i + 1)


class EIInput:
    """
    Wayland-native input injector using libei sender context.

    Usage:
        ei = EIInput(ei_fd, screen_width, screen_height)
        ei.connect(timeout=5.0)
        ei.click(500, 300)
        ei.type_text("hello world")
        ei.close()
    """

    def __init__(self, ei_fd: int, screen_width: int, screen_height: int):
        self._fd = ei_fd
        self._width = screen_width    # PipeWire frame width (physical pixels)
        self._height = screen_height  # PipeWire frame height (physical pixels)
        self._ei = None
        self._pointer_dev = None   # absolute device (event delivery + button context)
        self._rel_dev = None       # relative device (hardware cursor visual movement)
        self._keyboard_dev = None
        self._seq = 0
        # EIS region coordinate space (logical pixels).  Set during connect().
        self._region_x: int = 0
        self._region_y: int = 0
        self._region_w: int = screen_width
        self._region_h: int = screen_height
        self._pointer_started: bool = False
        self._rel_started: bool = False
        # Tracked cursor position in EIS space for relative motion deltas.
        self._cur_x: float = 0.0
        self._cur_y: float = 0.0

    def connect(self, timeout: float = 10.0):
        """Initialize libei and negotiate capabilities with the compositor."""
        self._ei = _libei.ei_new_sender(None)
        if not self._ei:
            raise RuntimeError("ei_new_sender() returned NULL")

        _libei.ei_configure_name(self._ei, b"portal-use")

        ret = _libei.ei_setup_backend_fd(self._ei, ctypes.c_int(self._fd))
        if ret != 0:
            raise RuntimeError(f"ei_setup_backend_fd() failed: {ret}")

        ei_fd = _libei.ei_get_fd(self._ei)
        deadline = time.monotonic() + timeout
        connected = False
        seat = None

        while time.monotonic() < deadline:
            r, _, _ = select.select([ei_fd], [], [], 0.1)
            if r:
                _libei.ei_dispatch(self._ei)

            ev = _libei.ei_get_event(self._ei)
            while ev:
                etype = _libei.ei_event_get_type(ev)

                if etype == EI_EVENT_CONNECT:
                    connected = True

                elif etype == EI_EVENT_SEAT_ADDED:
                    seat = _libei.ei_event_get_seat(ev)
                    # Request pointer (relative) + pointer absolute + keyboard capabilities.
                    # POINTER (relative) creates a trackpad-style device whose motion
                    # updates the compositor's hardware cursor overlay (visible on screen).
                    # POINTER_ABSOLUTE provides coordinate context for button events.
                    _libei.ei_seat_bind_capabilities(
                        seat,
                        ctypes.c_int(EI_DEVICE_CAP_POINTER),
                        ctypes.c_int(EI_DEVICE_CAP_POINTER_ABSOLUTE),
                        ctypes.c_int(EI_DEVICE_CAP_BUTTON),
                        ctypes.c_int(EI_DEVICE_CAP_SCROLL),
                        ctypes.c_int(EI_DEVICE_CAP_KEYBOARD),
                        None,  # NULL sentinel
                    )
                    

                elif etype == EI_EVENT_DEVICE_ADDED:
                    dev = _libei.ei_event_get_device(ev)
                    has_abs = _libei.ei_device_has_capability(dev, EI_DEVICE_CAP_POINTER_ABSOLUTE)
                    has_rel = _libei.ei_device_has_capability(dev, EI_DEVICE_CAP_POINTER)
                    has_btn = _libei.ei_device_has_capability(dev, EI_DEVICE_CAP_BUTTON)
                    has_kbd = _libei.ei_device_has_capability(dev, EI_DEVICE_CAP_KEYBOARD)
                    dev_type = _libei.ei_device_get_type(dev)  # 1=VIRTUAL, 2=PHYSICAL
                    print(
                        f"[input] DEVICE_ADDED type={'VIRTUAL' if dev_type==1 else 'PHYSICAL'}"
                        f" abs={has_abs} rel={has_rel} btn={has_btn} kbd={has_kbd}",
                        file=sys.stderr, flush=True,
                    )
                    if has_abs:
                        self._pointer_dev = _libei.ei_device_ref(dev)
                        # Query the EIS region so we know the coordinate space.
                        # ei_device_pointer_motion_absolute takes logical-pixel
                        # coords within this region, NOT raw physical frame pixels.
                        region = _libei.ei_device_get_region(dev, 0)
                        if region:
                            self._region_x = _libei.ei_region_get_x(region) or 0
                            self._region_y = _libei.ei_region_get_y(region) or 0
                            self._region_w = _libei.ei_region_get_width(region) or self._width
                            self._region_h = _libei.ei_region_get_height(region) or self._height
                        print(
                            f"[input] pointer (abs): region=({self._region_x},{self._region_y})"
                            f" size={self._region_w}x{self._region_h}"
                            f"  frame={self._width}x{self._height}",
                            file=sys.stderr, flush=True,
                        )
                    if has_rel and not has_abs:
                        # Separate relative (trackpad) device — updates hardware cursor.
                        self._rel_dev = _libei.ei_device_ref(dev)
                        print("[input] pointer (rel/trackpad): registered", file=sys.stderr, flush=True)
                    if has_kbd:
                        self._keyboard_dev = _libei.ei_device_ref(dev)
                        print("[input] DEVICE_ADDED keyboard", file=sys.stderr, flush=True)

                elif etype == EI_EVENT_DEVICE_RESUMED:
                    # Device is now active — MUST call start_emulating before sending events.
                    # This event may arrive in a later dispatch batch than DEVICE_ADDED,
                    # so we must NOT break out of the connect loop until we see it.
                    dev = _libei.ei_event_get_device(ev)
                    if dev == self._pointer_dev:
                        self._seq += 1
                        _libei.ei_device_start_emulating(dev, ctypes.c_uint32(self._seq))
                        self._pointer_started = True
                        print("[input] pointer (abs) started emulating", file=sys.stderr, flush=True)
                    elif self._rel_dev and dev == self._rel_dev:
                        self._seq += 1
                        _libei.ei_device_start_emulating(dev, ctypes.c_uint32(self._seq))
                        self._rel_started = True
                        print("[input] pointer (rel) started emulating", file=sys.stderr, flush=True)
                    elif dev == self._keyboard_dev:
                        self._seq += 1
                        _libei.ei_device_start_emulating(dev, ctypes.c_uint32(self._seq))
                        print("[input] keyboard device started emulating", file=sys.stderr, flush=True)

                _libei.ei_event_unref(ev)
                ev = _libei.ei_get_event(self._ei)

            # Wait for DEVICE_RESUMED (start_emulating) on all devices before proceeding.
            # If we break early, motion events hit a device that was never told to
            # start emulating and are silently dropped.
            if (connected
                    and self._pointer_dev and self._pointer_started
                    and self._rel_dev and self._rel_started
                    and self._keyboard_dev):
                break

        if not connected:
            raise RuntimeError("libei: EI_EVENT_CONNECT not received")
        if not self._pointer_dev:
            raise RuntimeError("libei: no pointer device received from compositor")
        if not self._keyboard_dev:
            raise RuntimeError("libei: no keyboard device received from compositor")
        if not self._pointer_started:
            raise RuntimeError("libei: pointer device never resumed (ei_device_start_emulating not called)")
        if not self._rel_dev:
            raise RuntimeError("libei: no relative pointer device received (EI_DEVICE_CAP_POINTER not granted)")
        if not self._rel_started:
            raise RuntimeError("libei: relative pointer device never resumed")

        # Home the cursor to (0,0) by sending a large negative delta.
        # The compositor clamps to the screen boundary, leaving the cursor at the
        # top-left corner.  We then know _cur_x=0, _cur_y=0 so delta-tracking
        # for subsequent move() calls is accurate from a known starting position.
        _libei.ei_device_pointer_motion(
            self._rel_dev,
            ctypes.c_double(-99999.0), ctypes.c_double(-99999.0)
        )
        _libei.ei_device_frame(self._rel_dev, ctypes.c_uint64(self._now_us()))
        fn = getattr(_libei, "ei_flush", None)
        if fn:
            fn(self._ei)
        self._cur_x = 0.0
        self._cur_y = 0.0

        print(
            f"[input] libei connected. abs={self._pointer_dev} rel={self._rel_dev} keyboard={self._keyboard_dev}",
            file=sys.stderr, flush=True,
        )

    def _pump(self):
        """Drain any pending libei events (keeps the connection alive)."""
        ei_fd = _libei.ei_get_fd(self._ei)
        r, _, _ = select.select([ei_fd], [], [], 0.0)
        if r:
            _libei.ei_dispatch(self._ei)
            ev = _libei.ei_get_event(self._ei)
            while ev:
                _libei.ei_event_unref(ev)
                ev = _libei.ei_get_event(self._ei)


    def _now_us(self) -> int:
        return int(time.monotonic() * 1_000_000)

    def _to_eis(self, x: float, y: float) -> tuple[float, float]:
        """
        Convert physical frame-pixel coords to EIS logical region coords.

        PipeWire gives us frames in physical pixels.
        EIS wants logical-pixel coords within the device region.
        On HiDPI (e.g. 4K/2× scale): frame=3840×2160, region=1920×1080 →
        every raw physical coord would land 2× outside the region and be
        silently ignored by the compositor.
        """
        eis_x = self._region_x + (x / self._width)  * self._region_w
        eis_y = self._region_y + (y / self._height) * self._region_h
        return eis_x, eis_y

    def move(self, x: float, y: float):
        self._pump()
        eis_x, eis_y = self._to_eis(x, y)

        # Relative motion: sends delta to the trackpad-style device.
        # The compositor updates the DRM hardware cursor overlay in response,
        # making the cursor visually move on screen.
        if self._rel_dev:
            dx = eis_x - self._cur_x
            dy = eis_y - self._cur_y
            _libei.ei_device_pointer_motion(
                self._rel_dev,
                ctypes.c_double(dx), ctypes.c_double(dy)
            )
            _libei.ei_device_frame(self._rel_dev, ctypes.c_uint64(self._now_us()))
            self._cur_x = eis_x
            self._cur_y = eis_y

        # Absolute motion: keeps the abs device's position current so that
        # subsequent button() calls (which use _pointer_dev) land at the right
        # coordinate even if the compositor uses the last absolute position.
        _libei.ei_device_pointer_motion_absolute(
            self._pointer_dev,
            ctypes.c_double(eis_x), ctypes.c_double(eis_y)
        )
        _libei.ei_device_frame(self._pointer_dev, ctypes.c_uint64(self._now_us()))

    def button(self, code: int, pressed: bool):
        self._pump()
        _libei.ei_device_button_button(
            self._pointer_dev,
            ctypes.c_uint32(code),
            ctypes.c_bool(pressed)
        )
        _libei.ei_device_frame(self._pointer_dev, ctypes.c_uint64(self._now_us()))

    def click(self, x: float, y: float, button: str = "left", double: bool = False):
        btn = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}.get(button, BTN_LEFT)
        self.move(x, y)
        for _ in range(2 if double else 1):
            self.button(btn, True)
            time.sleep(0.05)
            self.button(btn, False)
            if double:
                time.sleep(0.08)

    def scroll(self, x: float, y: float, direction: str, amount: float = 3.0):
        self.move(x, y)
        self._pump()
        dx = dy = 0.0
        if direction == "up":    dy = -amount
        elif direction == "down": dy = amount
        elif direction == "left": dx = -amount
        elif direction == "right": dx = amount
        _libei.ei_device_scroll_delta(
            self._pointer_dev,
            ctypes.c_double(dx), ctypes.c_double(dy)
        )
        _libei.ei_device_frame(self._pointer_dev, ctypes.c_uint64(self._now_us()))

    def key(self, code: int, pressed: bool):
        self._pump()
        _libei.ei_device_keyboard_key(
            self._keyboard_dev,
            ctypes.c_uint32(code),
            ctypes.c_bool(pressed)
        )
        _libei.ei_device_frame(self._keyboard_dev, ctypes.c_uint64(self._now_us()))

    def key_combo(self, keys_str: str):
        """Press a combo like 'ctrl+c', 'alt+tab', 'enter'."""
        parts = [k.strip().lower() for k in keys_str.split("+")]
        codes = []
        for part in parts:
            if part not in KEY_CODES:
                raise ValueError(f"Unknown key: {part!r}")
            codes.append(KEY_CODES[part])
        for code in codes:
            self.key(code, True)
            time.sleep(0.02)
        for code in reversed(codes):
            self.key(code, False)
            time.sleep(0.02)

    def type_text(self, text: str):
        """
        Type a string character by character.
        Raises ValueError on any untypeable character — no silent drops.
        """
        for ch in text:
            if ch in _SHIFT_MAP:
                # Shifted symbol — e.g. '!' -> shift + '1'
                base = _SHIFT_MAP[ch]
                if base not in KEY_CODES:
                    raise ValueError(
                        f"Cannot type {ch!r}: base key {base!r} not in key map"
                    )
                self.key(KEY_CODES["shift"], True)
                self.key(KEY_CODES[base], True)
                time.sleep(0.02)
                self.key(KEY_CODES[base], False)
                self.key(KEY_CODES["shift"], False)
                time.sleep(0.02)
            else:
                low = ch.lower()
                if low not in KEY_CODES:
                    raise ValueError(
                        f"Cannot type {ch!r} (U+{ord(ch):04X}): not in key map. "
                        f"Use computer_key for special keys."
                    )
                needs_shift = ch.isupper() or (ch != low and low in KEY_CODES)
                if needs_shift:
                    self.key(KEY_CODES["shift"], True)
                self.key(KEY_CODES[low], True)
                time.sleep(0.02)
                self.key(KEY_CODES[low], False)
                if needs_shift:
                    self.key(KEY_CODES["shift"], False)
                time.sleep(0.02)

    def close(self):
        if self._pointer_dev:
            _libei.ei_device_stop_emulating(self._pointer_dev)
            _libei.ei_device_unref(self._pointer_dev)
            self._pointer_dev = None
        if self._rel_dev:
            _libei.ei_device_stop_emulating(self._rel_dev)
            _libei.ei_device_unref(self._rel_dev)
            self._rel_dev = None
        if self._keyboard_dev:
            _libei.ei_device_stop_emulating(self._keyboard_dev)
            _libei.ei_device_unref(self._keyboard_dev)
            self._keyboard_dev = None
        if self._ei:
            _libei.ei_disconnect(self._ei)
            _libei.ei_unref(self._ei)
            self._ei = None
