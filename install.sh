#!/usr/bin/env bash
# portal-use installer for Ubuntu 26.04+ (GNOME Wayland)
# Usage: bash install.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_DIR/.venv"

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
"$VENV/bin/pip" install mcp dbus-next Pillow --quiet

echo "==> Registering MCP server with Claude Code..."
if command -v claude &>/dev/null; then
    claude mcp add --scope user portal-use -- \
        "$VENV/bin/python" "$REPO_DIR/server.py"
    echo "    Registered. Run 'claude mcp list' to verify."
else
    echo "    Claude Code not found — add manually:"
    echo ""
    echo "    claude mcp add --scope user portal-use -- \\"
    echo "        $VENV/bin/python $REPO_DIR/server.py"
    echo ""
    echo "    Or for Claude Desktop, add to claude_desktop_config.json:"
    echo "    {"
    echo "      \"mcpServers\": {"
    echo "        \"portal-use\": {"
    echo "          \"command\": \"$VENV/bin/python\","
    echo "          \"args\": [\"$REPO_DIR/server.py\"]"
    echo "        }"
    echo "      }"
    echo "    }"
fi

echo ""
echo "Done. Next: open Claude and call computer_screenshot."
echo "Approve the GNOME consent dialog — happens once per login session."
