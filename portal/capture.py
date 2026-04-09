"""
PipeWire screen capture via GStreamer pipewiresrc.

Given a PipeWire remote fd and node id from the portal session,
captures a single frame and returns it as a PIL Image.
"""

import asyncio
import ctypes
import os
import sys
import threading
from io import BytesIO
from typing import Optional

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gst, GLib
from PIL import Image

Gst.init(None)


class ScreenCapture:
    def __init__(self, pw_fd: int, node_id: int):
        self._pw_fd = pw_fd
        self._node_id = node_id
        self._pipeline: Optional[Gst.Pipeline] = None
        self._loop: Optional[GLib.MainLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._last_frame: Optional[bytes] = None
        self._frame_event = threading.Event()
        self._frame_lock = threading.Lock()
        self._width = 0
        self._height = 0

    def start(self):
        """Start the GStreamer pipeline capturing from PipeWire."""
        # pipewiresrc with fd + path (node id) — same approach as GNOME Screen Cast
        pipeline_str = (
            f"pipewiresrc fd={self._pw_fd} path={self._node_id} "
            f"do-timestamp=true ! "
            f"videoconvert ! "
            f"video/x-raw,format=RGB ! "
            f"appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false"
        )
        self._pipeline = Gst.parse_launch(pipeline_str)

        sink = self._pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample)

        self._loop = GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._loop.run, daemon=True)
        self._loop_thread.start()

        bus = self._pipeline.get_bus()
        bus.add_watch(GLib.PRIORITY_DEFAULT, self._on_bus_message, None)

        self._pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
        if self._loop:
            self._loop.quit()

    def _on_new_sample(self, sink) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = structure.get_value("width")
        height = structure.get_value("height")

        buf = sample.get_buffer()
        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR

        try:
            data = bytes(map_info.data)
        finally:
            buf.unmap(map_info)

        with self._frame_lock:
            self._last_frame = data
            self._width = width
            self._height = height

        self._frame_event.set()
        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus, message, _data) -> bool:
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[capture] GStreamer error: {err} — {debug}", file=sys.stderr, flush=True)
        return True

    def grab_frame(self, timeout: float = 5.0) -> Optional[Image.Image]:
        """
        Wait for next frame and return it as a PIL Image.
        Resets the event so the next call waits for a new frame.
        """
        self._frame_event.clear()
        got = self._frame_event.wait(timeout=timeout)
        if not got:
            return None

        with self._frame_lock:
            data = self._last_frame
            w, h = self._width, self._height

        if not data or w == 0 or h == 0:
            return None

        return Image.frombytes("RGB", (w, h), data)


def scale_image_for_api(img: Image.Image, max_long_edge: int = 1568) -> tuple[Image.Image, float]:
    """
    Scale image so the long edge <= max_long_edge.
    Returns (scaled_image, scale_factor) where scale_factor < 1 means scaled down.
    scale_factor is applied to coordinates: physical = logical * (1 / scale_factor).
    """
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= max_long_edge:
        return img, 1.0

    scale = max_long_edge / long_edge
    new_w = int(w * scale)
    new_h = int(h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS), scale


def image_to_png_b64(img: Image.Image) -> str:
    """Encode PIL Image to base64 PNG string."""
    import base64
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()
