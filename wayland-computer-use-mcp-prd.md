# PRD: Wayland-Native Computer Use MCP Server

**Project Codename:** `portal-use` (working title)
**Author:** JohnO (johnohhh1)
**Date:** March 30, 2026
**Status:** Pre-Development / Scoping

---

## 1. Problem Statement

Every existing AI computer-use tool for Linux relies on X11-only mechanisms (xdotool + scrot) or unstable kernel-level hacks (ydotool + uinput). With all major Linux desktops defaulting to Wayland — Ubuntu 26.04, Fedora 41+, KDE Plasma 6+ — these tools are either broken or require the user to run a legacy X11 session.

Anthropic's own Cowork computer use is macOS-only (Accessibility framework). On Linux, Cowork falls back to browser-only control via the Chrome extension, which cannot interact with native desktop applications (terminals, file managers, IDEs, system settings, or anything outside a browser tab).

**No MCP server or AI agent tool exists that provides native Wayland desktop control using the correct, standards-compliant API path.**

---

## 2. Proposed Solution

Build a stdio-based MCP server that provides full desktop computer-use capabilities (screenshot, click, type, scroll, move) on Wayland using:

- **XDG Desktop Portal** (`org.freedesktop.portal.RemoteDesktop` + `org.freedesktop.portal.ScreenCast`) for session negotiation and permissions
- **PipeWire** for screen capture (frame grabbing from portal-provided streams)
- **libei** (Emulated Input) for mouse and keyboard injection via the portal's EIS connection

This is the same stack that GNOME Remote Desktop uses internally. We're essentially building a headless "remote desktop client" that runs locally and exposes its capabilities as MCP tools for AI agents.

---

## 3. Competitive Landscape & Prior Art

### 3.1 Existing Computer-Use MCP Servers (All X11-Dependent)

| Project | Mechanism | Wayland? | Notes |
|---------|-----------|----------|-------|
| **computer-use-mcp** (domdomegg) | xdotool + screenshot | ❌ X11 only | Simple npx install; Claude Code/Desktop; "probably a bad idea" |
| **claude_code_computer_use_mcp** (SebastianBaltes) | xdotool + scrot + ImageMagick | ❌ X11 only | More mature; auto-scaling coordinates; Claude Code focused |
| **mcp-qemu-vm** (neanderthal) | SSH + xdotool inside QEMU VM | ❌ X11 inside VM | VM-based isolation; can't control host desktop |

### 3.2 Wayland Input Injection Approaches

| Approach | Mechanism | Root? | Wayland-native? | Issues |
|----------|-----------|-------|-----------------|--------|
| **xdotool** | X11 XTEST protocol | No | ❌ X11 only | Dead on Wayland |
| **ydotool** | /dev/uinput (kernel virtual device) | Yes | ⚠️ Works but hacky | Ghost input bugs, no window awareness, root required, daemon instability on Ubuntu |
| **wtype** | Wayland virtual-keyboard protocol | No | ⚠️ Partial | Keyboard only, no mouse, compositor-dependent |
| **libei via RemoteDesktop portal** | EIS socket from compositor | No | ✅ Correct path | No MCP wrapper exists yet |

### 3.3 Adaptable Open Source Projects

| Project | What It Does | License | Adaptable Components |
|---------|-------------|---------|---------------------|
| **gnome-remote-desktop** | Full RDP/VNC server using PipeWire + libei + Mutter API | GPL-2.0+ | Reference implementation for the exact portal flow we need; C/Meson |
| **lamco-rdp-server** | Rust-based Wayland-native RDP server; XDG Portal + PipeWire + libei | BSL-1.1 (→ Apache 2028) | Modern Rust implementation of the full pipeline; modular architecture; NVENC support |
| **hzy** (Hadhzy) | Python bindings for libei via snegg | MIT-ish | Direct Python API for libei; part of "slodon" ecosystem; early stage but exactly what we need for input injection |
| **input-leap** (libei PR #1594) | Synergy/Barrier replacement with libei + RemoteDesktop portal backend | GPL-2.0 | Proven libei integration via libportal; glib mainloop pattern; working code merged |
| **wayfarer** | GNOME screen recorder using ScreenCast portal + PipeWire | GPL-3.0 | PipeWire frame capture from portal; GStreamer pipeline; token persistence |

### 3.4 Key Libraries

| Library | Purpose | Language | Maturity |
|---------|---------|----------|----------|
| **libei** / **libeis** | Emulated input (client/server) | C | Stable (1.0+); maintained by Red Hat (Peter Hutterer) |
| **libportal** | Simplified XDG portal D-Bus interaction | C + GLib | Stable; used by input-leap, GNOME apps |
| **dbus-next** | Async D-Bus client for Python | Python | Stable; asyncio-native |
| **hzy** | Python bindings for libei | Python | Early; MIT; directly usable |
| **pipewiresrc** / **GStreamer** | PipeWire frame capture | C/Python | Stable; OBS, GNOME, KDE all use this |

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────┐
│                    AI Agent                          │
│         (Claude Code / Cowork / Any MCP Client)      │
└────────────────────┬────────────────────────────────┘
                     │ stdio (MCP protocol)
                     │
┌────────────────────▼────────────────────────────────┐
│              portal-use MCP Server                   │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  Screenshot   │  │    Input     │  │  Display   │ │
│  │   Manager     │  │   Manager    │  │   Info     │ │
│  │              │  │              │  │            │ │
│  │  PipeWire    │  │  libei via   │  │  Portal    │ │
│  │  stream →    │  │  EIS fd from │  │  session   │ │
│  │  frame grab  │  │  RemoteDesk  │  │  metadata  │ │
│  │  → scale     │  │  portal      │  │            │ │
│  │  → encode    │  │              │  │            │ │
│  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
│         │                 │                │         │
│  ┌──────▼─────────────────▼────────────────▼──────┐ │
│  │         Portal Session Manager                  │ │
│  │                                                 │ │
│  │  D-Bus → org.freedesktop.portal.RemoteDesktop   │ │
│  │  D-Bus → org.freedesktop.portal.ScreenCast      │ │
│  │                                                 │ │
│  │  Session lifecycle: create → select sources →   │ │
│  │  select devices → start → get EIS fd →          │ │
│  │  open PipeWire remote                           │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
                     │
          D-Bus + PipeWire + libei
                     │
┌────────────────────▼────────────────────────────────┐
│              XDG Desktop Portal                      │
│    (xdg-desktop-portal-gnome / -kde / -wlr)          │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│           Wayland Compositor                         │
│        (Mutter / KWin / wlroots)                     │
└──────────────────────────────────────────────────────┘
```

---

## 5. MCP Tool Interface

### 5.1 Tools Exposed

| Tool Name | Parameters | Description |
|-----------|-----------|-------------|
| `computer_screenshot` | `region?` (x, y, w, h) | Capture full desktop or region; returns base64 PNG scaled to API constraints |
| `computer_click` | `x`, `y`, `button?` (left/right/middle), `click_type?` (single/double/triple) | Click at coordinates |
| `computer_move` | `x`, `y` | Move cursor to coordinates |
| `computer_type` | `text` | Type text string into focused window |
| `computer_key` | `keys` (e.g. "ctrl+c", "alt+tab", "enter") | Press key combination |
| `computer_scroll` | `x`, `y`, `direction` (up/down/left/right), `amount?` | Scroll at position |
| `computer_drag` | `start_x`, `start_y`, `end_x`, `end_y`, `button?` | Click-drag operation |
| `computer_display_info` | none | Returns resolution, scale factor, coordinate space |
| `computer_zoom` | `x`, `y`, `w`, `h` | Capture region at full (unscaled) resolution for reading small text |

### 5.2 Coordinate Space

All coordinates use a **scaled logical space** matching the approach in SebastianBaltes' MCP:
- Server detects physical resolution on session start
- Calculates scale factor to keep screenshots within API constraints (max 1568px long edge, max ~1.15M total pixels)
- All coordinates from the AI agent are in scaled space
- Server converts to physical coordinates before sending to libei
- This is transparent to the agent

---

## 6. Portal Session Flow (Technical Detail)

```
1. CreateSession()
   → D-Bus call to org.freedesktop.portal.RemoteDesktop
   → Returns session handle

2. SelectDevices(session, { types: KEYBOARD | POINTER })
   → Request keyboard + pointer emulation capabilities

3. SelectSources(session, { types: MONITOR, cursor_mode: EMBEDDED })
   → Request screen capture with cursor visible in stream

4. Start(session)
   → User gets ONE-TIME portal consent dialog
   → Returns: PipeWire streams[] + restore_token
   → Token can be persisted for subsequent sessions (no re-prompting)

5. ConnectToEIS(session)
   → Returns file descriptor for libei sender context
   → All subsequent input goes through this fd

6. OpenPipeWireRemote(session)
   → Returns fd for PipeWire remote
   → Connect pw_stream to capture frames

7. Operate:
   - Screenshot: grab latest PipeWire frame → scale → encode PNG → base64
   - Input: send events through libei sender context

8. Teardown:
   - Close libei context
   - Disconnect PipeWire stream
   - Close portal session
```

---

## 7. Implementation Plan

### Phase 1: Proof of Concept (Target: 1-2 sessions with Claude Code)

**Goal:** Screenshot + click working on Beast via MCP stdio

- [ ] Scaffold MCP server (Python, stdio transport)
- [ ] Implement portal session manager using `dbus-next`
- [ ] Establish PipeWire stream and grab a single frame
- [ ] Scale frame and return as base64 PNG
- [ ] Establish libei connection via portal EIS fd
- [ ] Send a mouse click event
- [ ] Test with Claude Code: `claude mcp add portal-use -- python3 /path/to/server.py`

**Dependencies to install:**
```bash
sudo apt install libei-dev libportal-dev pipewire-dev python3-dbus-next
pip install dbus-next pillow --break-system-packages
```

**Decision point:** Python with `dbus-next` + `hzy` (fast to prototype) vs Rust with libportal bindings (better performance, harder to write). Recommend Python for PoC, Rust rewrite if it works.

### Phase 2: Full Tool Suite

- [ ] All 9 tools from section 5.1
- [ ] Coordinate scaling system (auto-detect resolution, calculate scale factor)
- [ ] Key combination support (modifiers, special keys)
- [ ] Session token persistence (avoid re-prompting on restart)
- [ ] Error handling and graceful reconnection
- [ ] Screenshot optimization (DMA-BUF if available, fallback to memfd)

### Phase 3: Packaging & Distribution

- [ ] npm package for `npx` install (like domdomegg's approach)
- [ ] PyPI package as alternative
- [ ] One-liner install for Claude Code: `claude mcp add --scope user portal-use -- npx portal-use-mcp`
- [ ] README with compositor compatibility matrix
- [ ] Test on: GNOME/Mutter, KDE/KWin, Sway, Hyprland

### Phase 4: Advanced Features

- [ ] Window-aware operations (list windows, focus by title)
- [ ] OCR integration for text extraction from screenshots
- [ ] Clipboard read/write via portal Clipboard API
- [ ] Multi-monitor support (select monitor, cross-monitor operations)
- [ ] Fallback chain: portal → ydotool → xdotool (for maximum compatibility)
- [ ] X11 fallback detection (if WAYLAND_DISPLAY not set, use xdotool path)

---

## 8. Compositor Compatibility Matrix (Expected)

| Compositor | Portal Backend | ScreenCast | RemoteDesktop | libei/EIS | Status |
|------------|---------------|------------|---------------|-----------|--------|
| GNOME (Mutter) | xdg-desktop-portal-gnome | ✅ | ✅ | ✅ | Full support (reference impl) |
| KDE (KWin) | xdg-desktop-portal-kde | ✅ | ✅ | ✅ | Full support |
| Sway | xdg-desktop-portal-wlr | ✅ | ⚠️ Limited | ❌ Not yet | ScreenCast only; no EIS in wlroots yet |
| Hyprland | xdg-desktop-portal-hyprland | ✅ | ⚠️ Limited | ❌ Not yet | Same as wlroots |
| COSMIC | cosmic-portal | ✅ | ❌ | ❌ | Video only; blocked on Smithay libei |

**Primary target: GNOME on Ubuntu 26.04** (Beast's environment). KDE second. wlroots compositors would get screenshot-only until libei lands upstream.

---

## 9. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| Portal consent dialog appears every session | High (breaks unattended use) | Medium | Use `persist_mode=2` + `restore_token` to persist across sessions |
| libei Python bindings (hzy) are immature | Medium | High | Fallback to CFFI direct bindings against libei.so; or subprocess to a small C helper |
| PipeWire frame capture latency too high | Medium | Low | DMA-BUF zero-copy path; only grab frames on screenshot request, not continuous |
| wlroots compositors lack EIS support | Medium | High | Document as known limitation; implement screenshot-only mode for those compositors |
| GNOME portal dialog steals focus mid-operation | Low | Medium | Session persistence eliminates after first run |
| Anthropic ships native Linux computer use | Low (validates market) | Unknown | If they do, they'll likely need this exact stack; our work becomes reference impl or gets adopted |

---

## 10. Success Criteria

**MVP (Phase 1):**
- Claude Code can take a screenshot of the full Ubuntu desktop (not just browser)
- Claude Code can click a button in a native GTK application
- Claude Code can type text into a terminal emulator
- No root required; no xdotool; no kernel hacks
- Works on Wayland session without XWayland fallback

**Production (Phase 3):**
- `npx portal-use-mcp` install works on Ubuntu 24.04+ / Fedora 40+ / Arch
- Works with Claude Code, Claude Desktop, Cursor, and any MCP client
- Session persists across server restarts (no re-prompting)
- Coordinate scaling handles 4K, HiDPI, and multi-monitor setups

---

## 11. Licensing

**Recommended: MIT**

Rationale: Maximum adoption. The underlying libraries (libei, libportal, PipeWire) are LGPL/MIT. gnome-remote-desktop is GPL-2.0+ but we're not copying code — we're using the same public D-Bus APIs. MIT keeps the door open for Anthropic or anyone else to adopt/embed it.

---

## 12. Open Questions

1. **Does `hzy` (Python libei bindings) actually work on Ubuntu 26.04?** Needs testing.
2. **Can we avoid the portal consent dialog entirely for local use?** GNOME may allow this if the app is running as the session user and desktop sharing is already enabled (as it is on Beast).
3. **Should we support the legacy `NotifyPointerMotion` / `NotifyKeyboardKeycode` D-Bus methods as well as libei?** The portal docs say once EIS is connected, Notify* methods return errors. But older portals may not support EIS.
4. **Rust or Python?** Python is faster to ship. Rust is better long-term. Could ship Python PoC, then rewrite.
5. **Should this be an MCP server only, or also a standalone CLI tool?** A CLI (`portal-use screenshot`, `portal-use click 100 200`) would be useful for debugging and would essentially be the Wayland equivalent of xdotool.

---

## Appendix A: Reference Links

- [XDG RemoteDesktop Portal Spec](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
- [XDG ScreenCast Portal Spec](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.impl.portal.ScreenCast.html)
- [libei Documentation](https://libinput.pages.freedesktop.org/libei/)
- [libei Blog Post (Peter Hutterer)](http://who-t.blogspot.com/2020/08/libei-library-to-support-emulated-input.html)
- [gnome-remote-desktop (GitHub mirror)](https://github.com/GNOME/gnome-remote-desktop)
- [lamco-rdp-server (Rust, Wayland-native)](https://github.com/lamco-admin/lamco-rdp-server)
- [hzy - Python libei bindings](https://github.com/Hadhzy/hzy)
- [input-leap libei PR](https://github.com/input-leap/input-leap/pull/1594)
- [computer-use-mcp (domdomegg, X11)](https://github.com/domdomegg/computer-use-mcp)
- [claude_code_computer_use_mcp (SebastianBaltes, X11)](https://github.com/SebastianBaltes/claude_code_computer_use_mcp)
- [xdotool Wayland fragmentation writeup (semicomplete.com)](https://www.semicomplete.com/blog/xdotool-and-exploring-wayland-fragmentation/)
