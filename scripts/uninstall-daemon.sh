#!/bin/bash
set -euo pipefail

LABEL="com.ideaforge.daemon"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "IdeaForge daemon removed."