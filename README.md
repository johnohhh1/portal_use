# portal-use

[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey?logo=linux&logoColor=white)](https://kernel.org/)
[![Wayland](https://img.shields.io/badge/display-Wayland-blueviolet?logo=wayland)](https://wayland.freedesktop.org/)
[![GNOME](https://img.shields.io/badge/compositor-GNOME%2050+-4A86CF?logo=gnome&logoColor=white)](https://www.gnome.org/)
[![MCP](https://img.shields.io/badge/MCP-compatible-FF6B35)](https://modelcontextprotocol.io/)
[![Version](https://img.shields.io/badge/version-0.2.0-informational)](pyproject.toml)

**Wayland-native desktop computer use for AI agents.**

Full desktop control — screenshots, clicks, typing, scrolling, dragging — using only proper Wayland protocols. No X11 bridge, no virtual display, no VNC, no root access, no kernel hacks.

```
AI agent → MCP → portal-use → XDG Desktop Portal → compositor
                                     ↓                    ↓
                               PipeWire (screen)    libei (input)
```

The compositor handles consent. You approve once. Everything after that is automatic.

---

## How it works

| Layer | What it does |
|-------|-------------|
| **XDG Desktop Portal** | `RemoteDesktop` + `ScreenCast` portals negotiate consent and hand back two file descriptors: a PipeWire node for screen capture and an EIS socket for input injection |
| **PipeWire → GStreamer** | `pipewiresrc` captures frames in real time; `videoconvert` normalizes to RGB; `appsink` hands PIL the raw bytes |
| **libei (sender)** | Emulated Input library sends relative pointer motion, absolute pointer events, button presses, scroll, and keyboard events through the EIS socket — the compositor processes them exactly like physical hardware |
| **MCP server** | Wraps everything in a `stdio`-transport MCP server with 11 tools |

The consent dialog fires **once** when the server first starts. After that the session stays alive for all tool calls. On supported compositors a restore token is saved to skip the dialog on subsequent server restarts.

---

## Requirements

**OS**: Ubuntu 26.04 (Resolute Raccoon) or any GNOME 50+ Wayland compositor  
**Not supported**: X11, KDE wlroots (EIS partial), headless

```bash
sudo apt install \
    python3-gi python3-gi-cairo \
    gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-pipewire \
    libei1 libei-dev \
    xdg-desktop-portal-gnome \
    gir1.2-glib-2.0
```

---

## Install

```bash
git clone https://github.com/johnohhh1/portal_use
cd portal_use
bash install.sh
```

`install.sh` installs system packages, creates a venv, installs Python deps, and registers the MCP server with Claude Code automatically.

**Manual install:**
```bash
sudo apt-get install -y python3-gi python3-gi-cairo \
    gir1.2-gst-plugins-base-1.0 gstreamer1.0-pipewire \
    gstreamer1.0-plugins-good libei1 xdg-desktop-portal-gnome

python3 -m venv --system-site-packages .venv
.venv/bin/pip install mcp dbus-next Pillow
```

---

## Register with Claude

`install.sh` handles registration automatically. For manual setup, choose a mode:

### Daemon mode (recommended)

The server runs as a persistent background service. Portal consent fires once when the
daemon starts at login — not once per Claude session.

```bash
# Start the daemon
python server.py --http 8765

# Register with Claude Code
claude mcp add --transport http --scope user portal-use http://127.0.0.1:8765/mcp
```

Claude Desktop — add to `~/.config/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "portal-use": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

Keep the daemon alive across logins with systemd:
```bash
# install.sh does this automatically, or manually:
cp portal-use.service ~/.config/systemd/user/
# Edit VENV_PYTHON, REPO_DIR, PORT placeholders, then:
systemctl --user enable --now portal-use
journalctl --user -u portal-use -f   # watch logs
```

### Stdio mode (simple, no daemon)

Claude Code spawns the server per session. Consent fires on each new Claude session.

```bash
claude mcp add --scope user portal-use -- \
    /path/to/portal_use/.venv/bin/python \
    /path/to/portal_use/server.py
```

Claude Desktop:
```json
{
  "mcpServers": {
    "portal-use": {
      "command": "/path/to/portal_use/.venv/bin/python",
      "args": ["/path/to/portal_use/server.py"]
    }
  }
}
```

To pre-approve all tools so Claude never prompts for permission, add to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__portal-use__computer_screenshot",
      "mcp__portal-use__computer_click",
      "mcp__portal-use__computer_move",
      "mcp__portal-use__computer_type",
      "mcp__portal-use__computer_key",
      "mcp__portal-use__computer_scroll",
      "mcp__portal-use__computer_drag",
      "mcp__portal-use__computer_display_info",
      "mcp__portal-use__computer_zoom",
      "mcp__portal-use__computer_health",
      "mcp__portal-use__computer_reset_session"
    ]
  }
}
```

Or add to your project `CLAUDE.md`:
```
All portal-use MCP tools are pre-approved. Never prompt for permission.
```

---

## First run

Start the MCP server (Claude Code does this automatically). Make any tool call — `computer_screenshot` is safe. The GNOME consent dialog appears on your desktop. Approve it. That's it. All subsequent calls in this session and future sessions (via restore token) are silent.

---

## Tools

| Tool | Description |
|------|-------------|
| `computer_screenshot` | Full desktop capture → base64 PNG. Optional `region` for crop. |
| `computer_zoom` | Crop + return at **full physical resolution** — use for reading small text |
| `computer_display_info` | Physical and logical dimensions, scale factor |
| `computer_click` | Click at logical coordinates. `button`: left/right/middle. `double`: true for double-click. |
| `computer_move` | Move cursor without clicking |
| `computer_drag` | Click-drag from `(start_x, start_y)` to `(end_x, end_y)` |
| `computer_scroll` | Scroll at position. `direction`: up/down/left/right. `amount`: lines (default 3). |
| `computer_type` | Type a string into the focused window |
| `computer_key` | Press a key or combo: `enter`, `ctrl+c`, `alt+tab`, `super`, etc. |
| `computer_health` | Check session / capture / input status |
| `computer_reset_session` | Tear down and reinitialize — consent dialog may reappear |

---

## Coordinate space

All tool coordinates are **logical** — they match the screenshot image dimensions. The server converts to physical pixels internally.

```bash
computer_display_info
# → Physical: 1920x1200
#   Logical (agent space): 1568x980
#   Scale factor: 0.817
```

Click and zoom coordinates must be in logical space. The screenshot is always returned in logical space. If you measure a coordinate from the screenshot image, use it directly — no math needed.

---

## Common patterns

### Open an app

```
computer_key keys="super"          # open Activities / app launcher
computer_screenshot                # see the search box
computer_type text="firefox"       # search
computer_key keys="enter"          # open top result
computer_screenshot                # verify
```

### Read small text

```
computer_screenshot                # get overview, find region of interest
computer_zoom x=400 y=300 width=200 height=80   # full-res crop
```

### Right-click context menu

```
computer_click x=25 y=47 button="right"   # open context menu
computer_screenshot                        # see menu items
computer_click x=65 y=72                  # click the item
```

### Terminal workflow

```
computer_click x=400 y=300        # click terminal to focus
computer_type text="git status"
computer_key keys="enter"
computer_screenshot                # read output (use zoom for small fonts)
```

---

## Troubleshooting

**Consent dialog doesn't appear**  
Check that `xdg-desktop-portal-gnome` is installed and you're running a GNOME Wayland session (not X11).

**`libei: no relative pointer device`**  
Your compositor didn't grant `EI_DEVICE_CAP_POINTER`. Try `computer_reset_session`.

**`Screenshot failed: no frame`**  
PipeWire pipeline stalled. Run `computer_health` to diagnose. If capture shows stalled, `computer_reset_session`.

**Activities overview keeps opening**  
The cursor initializes at (0,0) which hits the GNOME hot corner. Call `computer_move` to a safe position immediately after startup before clicking anything.

**Input not delivered (clicks don't land)**  
Run `computer_health`. If input shows disconnected, `computer_reset_session`. Make sure `libei1` is installed.

**Force re-consent (delete restore token)**  
```bash
rm -rf ~/.config/portal-use/
```

**See raw server logs**  
```bash
.venv/bin/python server.py
```
MCP stdio runs on stdin/stdout; all diagnostics go to stderr.

---

## Architecture notes

### Why two pointer devices?

portal-use registers two libei devices simultaneously:

- **`POINTER_ABSOLUTE`** — sends logical-pixel coordinates directly within the EIS region. Used for button events (clicks) so they land at exactly the specified coordinate regardless of cursor position.
- **`POINTER` (relative / trackpad)** — sends `(dx, dy)` deltas. This is the device that causes the compositor's DRM hardware cursor overlay to actually move visually on screen.

Absolute motion alone doesn't update the hardware cursor on GNOME 50+. Relative motion does. Both are needed: relative to move the cursor, absolute to anchor button coordinates.

### Coordinate pipeline

```
agent logical (x, y)
    → server.py: logical_to_physical → (x / scale, y / scale)
    → input.py: _to_eis → maps frame pixels to EIS region coords
    → libei: ei_device_pointer_motion_absolute(eis_x, eis_y)
              ei_device_pointer_motion(dx, dy)   ← hardware cursor
```

On a non-HiDPI 1920×1200 display: frame = EIS region = physical, so the pipeline is 1:1 modulo the scale factor applied at the top.

---

## Security

portal-use uses only portal-mediated access. The compositor enforces consent — no root, no evdev direct access, no kernel module. The restore token (`~/.config/portal-use/session_token`) is a compositor-issued opaque string; it contains no screen content and cannot be used outside your session.

