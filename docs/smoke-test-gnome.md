# portal-use GNOME Smoke Test

**Environment**: Ubuntu 26.04+, GNOME 45+, Wayland session, NVIDIA or Mesa GPU  
**Run before every release.**

## Setup

- [ ] Fresh terminal in Wayland session (not SSH, not X11)
- [ ] Restore token cleared: `rm -f ~/.config/portal-use/session_token`
- [ ] Server not running

## 1. First-run consent

- [ ] Start server: `.venv/bin/python server.py`
- [ ] Portal consent dialog appears on screen
- [ ] Approve the dialog
- [ ] Server logs: "Ready. WxH, scale=..."
- [ ] Restore token saved: `ls ~/.config/portal-use/session_token`

## 2. Screenshot

- [ ] Call `computer_screenshot` — returns image
- [ ] Image shows correct desktop content
- [ ] `computer_display_info` returns sensible dimensions

## 3. Restart with restore token

- [ ] Stop server (Ctrl+C)
- [ ] Start server again
- [ ] No consent dialog appears
- [ ] Server logs "Started. 1 stream(s). Token: ..."

## 4. Mouse input

- [ ] `computer_move` to center — cursor visibly moves
- [ ] `computer_click` on a known target (e.g. desktop icon) — click registers
- [ ] `computer_scroll` down in a scrollable window — scrolls
- [ ] `computer_drag` a window title bar — window moves

## 5. Keyboard input

- [ ] `computer_type "hello world"` in a text field — types correctly
- [ ] `computer_type "Hello, World! 123"` — uppercase, comma, space, exclamation, digits correct
- [ ] `computer_key "ctrl+a"` — selects all
- [ ] `computer_key "ctrl+c"` — copies
- [ ] `computer_key "enter"` — submits
- [ ] `computer_key "alt+tab"` — switches windows

## 6. Error paths

- [ ] `computer_type` with unsupported character (e.g. emoji) — returns explicit error, not silent drop
- [ ] `computer_key "ctrl+unknown"` — returns error "Unknown key: 'unknown'"

## 7. Recovery

- [ ] `computer_health` returns status of session/capture/input
- [ ] `computer_reset_session` reinitializes without process restart (consent may reappear)
- [ ] After reset, `computer_screenshot` works

## 8. Zoom

- [ ] `computer_zoom` on a region — returns full-res crop of that area

## Pass criteria

All checked items pass. Note any failures with compositor version and GPU driver version.
