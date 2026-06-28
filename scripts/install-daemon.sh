#!/bin/bash
# Install IdeaForge as a macOS LaunchAgent (runs at login, watches for USB recorder)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

ROOT="$(ideaforge_project_root)"
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
  chmod +x "$RUN_SCRIPT" "$SCRIPT_DIR/common.sh"
fi

ensure_ideaforge_venv "$ROOT"
check_daemon_secrets "$ROOT" || true

IDEAFORGE_BIN="$(resolve_ideaforge_bin "$ROOT")"
ENV_XML="$(plist_env_xml_from_dotenv "$ROOT")"
if [[ -z "$IDEAFORGE_BIN" ]]; then
  echo "ideaforge not found after venv setup." >&2
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
$ENV_XML    </dict>
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

load_launch_agent "$PLIST_PATH" "$LABEL"

echo "Installed IdeaForge daemon:"
echo "  Plist:  $PLIST_PATH"
echo "  Logs:   $LOG_DIR/daemon.log"
echo "  Venv:   $ROOT/venv"
echo "  Binary: $IDEAFORGE_BIN"
echo ""
echo "No need to activate the venv manually — the daemon uses the project venv above."
echo ""
echo "Commands:"
echo "  tail -f \"$LOG_DIR/daemon.log\"     # watch activity"
echo "  ./scripts/stop-daemon.sh               # stop (keeps install)"
echo "  launchctl kickstart -k $DOMAIN/$LABEL  # restart"
echo "  ./scripts/uninstall-daemon.sh          # stop and remove"