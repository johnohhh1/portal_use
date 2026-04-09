# portal-use Production Readiness PRD

## 1. Summary

`portal-use` is a Wayland-native MCP server for desktop computer use on Linux using the correct platform stack:

- XDG Desktop Portal
- PipeWire for screen capture
- libei for input injection
- stdio MCP transport for agent integration

The current implementation is already a serious prototype. It can likely serve as a local GNOME MVP, but it is not yet production-ready for external users because it lacks reliability guarantees, packaging, compatibility boundaries, recovery behavior, and operator-facing documentation.

This PRD defines what “production” means and what must be built to get there.

## 2. Goal

Ship `portal-use` as a reliable, installable, documented MCP server that works predictably on supported Linux desktop environments, primarily Ubuntu GNOME on Wayland, and can be used repeatedly without manual debugging.

## 3. Non-Goals

These are explicitly out of scope for v1 production:

- Full compositor coverage across all Wayland desktops
- OCR or semantic UI understanding
- Window introspection and focus-by-title
- Browser automation replacement
- Multi-user or remote-host orchestration
- Sandboxed security policy beyond what portals/compositor already enforce
- Perfect parity with Anthropic Cowork on macOS

## 4. Current State

### What already exists

The repo already has the core architecture in place:

- MCP server entrypoint with tool definitions in `server.py`
- Portal session lifecycle in `portal/session.py`
- PipeWire frame capture in `portal/capture.py`
- libei input injection in `portal/input.py`

### What works conceptually

- Portal session creation
- ScreenCast and RemoteDesktop negotiation
- PipeWire remote fd usage
- EIS fd usage for libei
- Tool surface for screenshot/click/move/type/key/scroll/drag/display info/zoom
- Basic coordinate scaling for screenshot/API constraints

### Main gaps

- Session restore token not actually reused
- Recovery behavior not robust
- Unsupported typing characters silently dropped
- No packaging or installer surface
- No compatibility policy
- No tests
- No operator docs
- No clear production error model

## 5. Production Definition

`portal-use` is “production-ready” when all of the following are true:

1. A new user can install it from documented instructions without reverse-engineering local setup.
2. On a supported environment, it reliably obtains consent, captures the screen, injects input, and survives repeated use.
3. Failure states are explicit, diagnosable, and recoverable.
4. Compatibility boundaries are documented and enforced.
5. The tool does not silently corrupt user intent, especially for input actions.
6. There is a repeatable test path before release.
7. The supported path is narrow and honest rather than broad and flaky.

## 6. Target User

### Primary user

Developer or power user on Ubuntu GNOME Wayland who wants AI desktop control through MCP without X11 hacks, root daemons, or browser-only control.

### Secondary user

Advanced Linux user willing to test on KDE Wayland if support is documented as experimental.

## 7. Target Environments

## v1 Supported

- Ubuntu 26.04+ GNOME Wayland
- xdg-desktop-portal + GNOME backend
- PipeWire enabled
- libei available
- Python environment with required bindings

## v1 Experimental

- KDE Plasma Wayland

## v1 Unsupported

- wlroots-based compositors for full input control if EIS path is incomplete
- X11 sessions
- Headless environments
- Non-portal fallback modes
- Remote display servers

## 8. Product Requirements

## A. Installation and Packaging

### Requirements

- Provide a standard package manifest, preferably `pyproject.toml`
- Support install via `pipx` or equivalent clean user-scoped install path
- Define and document native system dependencies
- Provide a single recommended MCP registration command
- Provide versioning

### Acceptance criteria

- Fresh Ubuntu machine can install from README
- `portal-use` can be launched without referencing John’s local venv path
- `claude mcp add` instructions are copy-pasteable

## B. Session Lifecycle and Consent

### Requirements

- First-run portal consent flow must be predictable
- Restore token must actually be reused if compositor/backend supports it
- Session startup must clearly log whether it is first-time consent or restored
- Session expiration must be detectable
- Session teardown must be clean

### Acceptance criteria

- First run shows one consent flow and succeeds
- Restart path avoids repeated prompts when supported
- Expired/broken sessions reinitialize without requiring process restart where possible
- Logs clearly show session state transitions

## C. Reliability and Recovery

### Requirements

- Detect broken `_session`, `_capture`, and `_input` states independently
- Reconnect on dropped PipeWire stream
- Reconnect on invalid EIS input context
- Handle portal call failures with structured errors
- Avoid wedging the server in a half-alive state

### Acceptance criteria

- If capture breaks, screenshot tool returns a useful error or self-recovers
- If input breaks, click/type/key tools either recover or fail explicitly
- Server remains usable after transient errors
- Recovery behavior is deterministic, not best-effort guesswork

## D. Input Fidelity

### Requirements

- `computer_type` must not silently drop unsupported characters
- Key mapping coverage must be expanded for common ASCII punctuation
- Unknown keys must return actionable errors
- Modifier combos must be validated
- Drag, scroll, and click behavior must be stable enough for normal UI usage

### Acceptance criteria

- Common shell commands, URLs, punctuation, and symbols type correctly
- Unsupported characters produce explicit failures
- `ctrl+c`, `ctrl+v`, `alt+tab`, `enter`, arrows, and common shortcuts work on supported environment
- Double-click and drag are reliable in repeated trials

## E. Screenshot Quality and Coordinate Contract

### Requirements

- Document coordinate space clearly
- Ensure crop and zoom paths behave consistently with scaled coordinates
- Preserve cursor visibility expectations
- Return images in a stable format/size policy
- Handle timeout and no-frame situations predictably

### Acceptance criteria

- Agent can use screenshot plus coordinates repeatedly without drift
- `computer_zoom` semantics are clearly documented
- Screenshot failures return machine-readable and human-readable cause
- Display info reflects actual coordinate contract

## F. MCP Tool Contract

### Requirements

- Finalize tool names and schemas
- Ensure descriptions match actual behavior
- Normalize success/failure response shape
- Add a health/status tool
- Add a diagnostics tool if useful

### Acceptance criteria

- Tool docs align with implementation
- Unknown-tool and invalid-input paths return clean errors
- Client can reliably distinguish image vs text responses
- There is at least one explicit readiness/health check path

## G. Documentation

### Requirements

- README with scope, install, usage, supported desktops, and limitations
- Troubleshooting section
- Compatibility matrix
- Security and consent explanation
- Release notes/changelog process

### Acceptance criteria

- A user who did not write the project can set it up
- Unsupported environments are called out before failure
- Known portal/compositor limitations are documented honestly

## H. Testing and Release Quality

### Requirements

- Add unit tests where possible for pure logic
- Add at least one smoke/integration checklist for GNOME
- Add pre-release manual validation steps
- Add linting/formatting/type-checking baseline
- Add release checklist

### Acceptance criteria

- Every release candidate passes the smoke checklist
- Typing/key parsing/coordinate conversion have automated coverage
- A broken release is less likely to come from trivial regressions

## 9. Functional Requirements

## Required v1 tools

- `computer_screenshot`
- `computer_click`
- `computer_move`
- `computer_type`
- `computer_key`
- `computer_scroll`
- `computer_drag`
- `computer_display_info`

## Optional for v1

- `computer_zoom`
- `computer_health`
- `computer_reset_session`

## 10. Non-Functional Requirements

## Performance

- Screenshot response should feel interactive on supported hardware
- Input actions should complete with low visible lag
- Startup time after first consent should be reasonable

## Reliability

- No silent dead-state after broken portal/capture/input
- No silent character loss in text entry
- Repeated tool calls should not progressively degrade

## Security and Privacy

- Use only portal-mediated permissions
- Never bypass consent with root-level hacks
- Clearly explain screen/input permission model to users
- Avoid storing sensitive material beyond what is needed for restore token

## Observability

- Structured stderr logs for startup, restore, failures, and reconnects
- Distinguishable error classes for portal, capture, input, and validation failures

## 11. UX Requirements

The user experience should feel like this:

1. Install package
2. Register MCP server
3. Run first tool call
4. Approve portal consent once
5. Use tools repeatedly without weird prompts or hidden failures

The user should not need to:

- Patch code
- Guess dependencies
- Discover compositor limitations by accident
- Restart manually after common failure modes
- Read source to understand coordinate behavior

## 12. Risks

## Technical risks

- Portal restore-token semantics vary by backend
- libei behavior may differ across compositors
- PipeWire frame path may behave differently under load or multi-monitor setups
- ctypes-based libei integration may remain brittle

## Product risks

- Trying to support too many compositors too early
- Claiming “Wayland support” too broadly when only GNOME is truly solid
- Silent failures damaging trust faster than explicit unsupported errors

## Mitigation

- Narrow v1 support to Ubuntu GNOME
- Enforce capability checks at startup
- Prefer explicit unsupported errors over unstable partial behavior
- Ship experimental support only behind documentation flags

## 13. Milestones

## Milestone 1: Production GNOME MVP

Scope:
- Packaging
- README
- real restore-token reuse
- reconnect logic
- improved typing/key mapping
- health/reset tools
- GNOME smoke validation

Exit criteria:
- Fresh Ubuntu GNOME user can install and use it repeatedly

## Milestone 2: Hardening

Scope:
- Better structured logging
- richer diagnostics
- more tests
- release process
- cleaner error taxonomy

Exit criteria:
- Can cut tagged releases with confidence

## Milestone 3: Experimental KDE Support

Scope:
- Validate KDE portal behavior
- document differences
- fix compatibility edge cases where feasible

Exit criteria:
- KDE marked supported or explicitly left experimental with clear caveats

## 14. Recommended Build Order

1. Add `pyproject.toml` and formal dependency list
2. Write real README and install instructions
3. Implement actual restore-token reuse
4. Add session/capture/input health detection and reset path
5. Fix `computer_type` fidelity and key validation
6. Add structured errors and a health tool
7. Add GNOME smoke checklist and a few unit tests
8. Cut first tagged release only for Ubuntu GNOME

## 15. Launch Criteria

Do not call it production until these are true:

- Install path is documented and repeatable
- GNOME Wayland path is validated end-to-end
- Restore/reconnect behavior is real, not aspirational
- Input fidelity is good enough for ordinary desktop work
- Unsupported environments fail honestly
- There is a release checklist and a support statement

## 16. Immediate Next Tasks

The highest-value concrete tasks are:

1. Implement restore-token reuse in the portal flow.
2. Add `computer_health` and `computer_reset_session`.
3. Refactor session state so dead capture/input/session components can be independently reinitialized.
4. Expand key map and make unsupported typing fail loudly.
5. Add `pyproject.toml` and README.
6. Write a GNOME manual smoke test doc.
