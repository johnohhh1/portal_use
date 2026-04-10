#!/usr/bin/env bash
# portal-use installer for Ubuntu 26.04+ (GNOME Wayland)
# Usage: bash install.sh [--port PORT]   (default port 8765)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_DIR/.venv"
PORT=8765

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "==> Installing system dependencies..."
sudo apt-get install -y \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-pipewire \
    gstreamer1.0-plugins-good \
    libei1 \
    xdg-desktop-portal-gnome

echo "==> Creating Python venv..."
python3 -m venv --system-site-packages "$VENV"

echo "==> Installing Python dependencies..."
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install "mcp[cli]" dbus-next Pillow uvicorn starlette --quiet

echo "==> Installing systemd user service (daemon mode, port $PORT)..."
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
sed \
    -e "s|VENV_PYTHON|$VENV/bin/python|g" \
    -e "s|REPO_DIR|$REPO_DIR|g" \
    -e "s|PORT|$PORT|g" \
    "$REPO_DIR/portal-use.service" > "$SERVICE_DIR/portal-use.service"
systemctl --user daemon-reload
systemctl --user enable --now portal-use
echo "    Daemon started on http://127.0.0.1:$PORT/mcp"
echo "    Approve the GNOME consent dialog that appears — happens once per login."

echo ""
echo "==> Registering MCP server with Claude Code (HTTP transport)..."
if command -v claude &>/dev/null; then
    # Remove any existing stdio registration first
    claude mcp remove portal-use --scope user 2>/dev/null || true
    claude mcp add --transport http --scope user portal-use \
        "http://127.0.0.1:$PORT/mcp"
    echo "    Registered. Run 'claude mcp list' to verify."
else
    echo "    Claude Code not found — add manually:"
    echo ""
    echo "    claude mcp add --transport http --scope user portal-use \\"
    echo "        http://127.0.0.1:$PORT/mcp"
fi

echo ""
echo "    For Claude Desktop, add to ~/.config/Claude/claude_desktop_config.json:"
cat <<JSON
    {
      "mcpServers": {
        "portal-use": {
          "url": "http://127.0.0.1:$PORT/mcp"
        }
      }
    }
JSON

echo ""
echo "Done. The daemon runs at login. Consent fires once per desktop session."
echo "Check status: systemctl --user status portal-use"
echo "View logs:    journalctl --user -u portal-use -f"
