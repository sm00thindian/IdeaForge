#!/bin/bash
# Install IdeaForge as a macOS LaunchAgent (runs at login, watches for USB recorder)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.ideaforge.daemon"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/ideaforge"
RUN_SCRIPT="$ROOT/scripts/run-daemon.sh"
DOMAIN="gui/$(id -u)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS only." >&2
  exit 1
fi

if [[ ! -x "$RUN_SCRIPT" ]]; then
  chmod +x "$RUN_SCRIPT"
fi

IDEAFORGE_BIN="$(command -v ideaforge || true)"
if [[ -z "$IDEAFORGE_BIN" ]]; then
  echo "ideaforge not found in PATH. Install the package first:" >&2
  echo "  cd \"$ROOT\" && pip install -e '.[all]'" >&2
  exit 1
fi

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
        <key>IDEAFORGE_BIN_OVERRIDE</key>
        <string>$IDEAFORGE_BIN</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$ROOT</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/daemon.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl kickstart -k "$DOMAIN/$LABEL"

echo "Installed IdeaForge daemon:"
echo "  Plist:  $PLIST_PATH"
echo "  Logs:   $LOG_DIR/daemon.log"
echo "  Binary: $IDEAFORGE_BIN"
echo ""
echo "The daemon watches /Volumes and runs the full pipeline when your recorder is plugged in."
echo ""
echo "Commands:"
echo "  tail -f \"$LOG_DIR/daemon.log\"     # watch activity"
echo "  ./scripts/stop-daemon.sh               # stop (keeps install)"
echo "  launchctl kickstart -k $DOMAIN/$LABEL  # restart"
echo "  ./scripts/uninstall-daemon.sh          # stop and remove"