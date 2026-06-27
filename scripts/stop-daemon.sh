#!/bin/bash
# Stop the IdeaForge LaunchAgent without uninstalling (plist is kept for restart)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

LABEL="com.ideaforge.daemon"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only." >&2
  exit 1
fi

if [[ ! -f "$PLIST_PATH" ]]; then
  echo "IdeaForge daemon is not installed (no plist at $PLIST_PATH)."
  echo "Install with: ./scripts/install-daemon.sh"
  exit 1
fi

unload_launch_agent "$PLIST_PATH" "$LABEL"

echo "IdeaForge daemon stopped."
echo ""
echo "Restart:"
echo "  ./scripts/install-daemon.sh"
echo ""
echo "Remove completely:"
echo "  ./scripts/uninstall-daemon.sh"