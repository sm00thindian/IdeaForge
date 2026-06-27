#!/bin/bash
# Stop the IdeaForge LaunchAgent without uninstalling (plist is kept for restart)
set -euo pipefail

LABEL="com.ideaforge.daemon"
DOMAIN="gui/$(id -u)"
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

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl disable "$DOMAIN/$LABEL" 2>/dev/null || true

echo "IdeaForge daemon stopped."
echo ""
echo "Restart:"
echo "  ./scripts/install-daemon.sh"
echo "  # or: launchctl enable $DOMAIN/$LABEL && launchctl kickstart -k $DOMAIN/$LABEL"
echo ""
echo "Remove completely:"
echo "  ./scripts/uninstall-daemon.sh"