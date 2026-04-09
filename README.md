# portal-use

Wayland-native desktop computer use MCP server. Uses XDG Desktop Portal + PipeWire + libei — no X11, no root, no kernel hacks.

**Supported**: Ubuntu 26.04+ GNOME on Wayland  
**Experimental**: KDE Plasma Wayland  
**Not supported**: X11, headless, wlroots without full EIS support

## Prerequisites

System packages (Ubuntu):
```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-pipewire libei-dev xdg-desktop-portal-gnome \
    gir1.2-glib-2.0
```

## Install

```bash
cd portal_use
python3 -m venv .venv
.venv/bin/pip install mcp dbus-next Pillow
```

## Register with Claude Code

```bash
claude mcp add --scope user portal-use -- \
    /path/to/portal_use/.venv/bin/python /path/to/portal_use/server.py
```

Replace `/path/to/portal_use` with your actual path.

## First run

On first use, a portal consent dialog appears on your desktop — approve it once. Subsequent restarts reuse a saved restore token to skip the dialog (on supported compositors).

## Tools

| Tool | Description |
|------|-------------|
| `computer_screenshot` | Capture the desktop, returns base64 PNG |
| `computer_click` | Click at logical coordinates |
| `computer_move` | Move cursor |
| `computer_type` | Type text |
| `computer_key` | Press key combos (e.g. `ctrl+c`) |
| `computer_scroll` | Scroll at position |
| `computer_drag` | Click and drag |
| `computer_display_info` | Get coordinate space info |
| `computer_zoom` | Capture region at full resolution |
| `computer_health` | Check session/capture/input status |
| `computer_reset_session` | Force session teardown and reinit |

## Coordinate space

All tool coordinates are **logical** — the screenshot image dimensions. Physical display resolution may differ (e.g. HiDPI). Use `computer_display_info` to confirm.

## Troubleshooting

**Portal consent dialog doesn't appear**: Make sure `xdg-desktop-portal-gnome` is installed and GNOME Shell is running.

**Black screen / no frames**: Check `journalctl --user -u gnome-remote-desktop -n 20`. PipeWire pipeline errors appear in stderr.

**Input not working**: Ensure `libei` is installed (`libei1` package). The EIS fd comes from the portal — make sure RemoteDesktop portal permission is granted.

**Delete restore token to force re-consent**:
```bash
rm ~/.config/portal-use/session_token
```

**Logs**: Run the server manually to see stderr:
```bash
.venv/bin/python server.py
```

## Limitations

- Only GNOME Wayland is fully supported in v1
- No window introspection or semantic UI understanding
- No OCR
- No multi-monitor coordinate stitching
- Headless environments not supported

## Security

portal-use uses only portal-mediated permissions. The compositor enforces consent. No root access is required or used. The restore token (stored at `~/.config/portal-use/session_token`) is a compositor-issued opaque string — it does not contain screen content.
