#!/bin/bash
# Stop IdeaForge menu bar status app and clear stale singleton lock
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

LABEL="com.ideaforge.menubar"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
LOCK_PATH="$HOME/Library/Application Support/IdeaForge/menubar.lock"

unload_launch_agent "$PLIST_PATH" "$LABEL" || true

pkill -f "ideaforge.menubar_app" 2>/dev/null || true
pkill -f "ideaforge-menubar" 2>/dev/null || true
pkill -f "scripts/run-menubar.sh" 2>/dev/null || true

rm -f "$LOCK_PATH"

echo "Stopped IdeaForge menu bar status."