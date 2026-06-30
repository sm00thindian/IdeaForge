#!/bin/bash
# Install IdeaForge menu bar status app as a macOS LaunchAgent
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

ROOT="$(ideaforge_project_root)"
LABEL="com.ideaforge.menubar"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/ideaforge"
RUN_SCRIPT="$ROOT/scripts/run-menubar.sh"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS only." >&2
  exit 1
fi

if [[ ! -x "$RUN_SCRIPT" ]]; then
  chmod +x "$RUN_SCRIPT" "$SCRIPT_DIR/common.sh"
fi

ensure_ideaforge_venv "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"
pip install -e "$ROOT/.[menubar]"

"$SCRIPT_DIR/stop-menubar.sh" >/dev/null 2>&1 || true
sleep 1

mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$RUN_SCRIPT</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$ROOT</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/menubar.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/menubar.err.log</string>
</dict>
</plist>
EOF

load_launch_agent "$PLIST_PATH" "$LABEL"

echo "Installed IdeaForge menu bar status:"
echo "  Plist:  $PLIST_PATH"
echo "  Logs:   $LOG_DIR/menubar.log"
echo "  Status: ~/Library/Application Support/IdeaForge/status.json"
echo ""
echo "Look for the IdeaForge icon in your menu bar."
echo "It updates live while the daemon processes recordings."