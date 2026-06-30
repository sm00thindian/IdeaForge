#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

LABEL="com.ideaforge.menubar"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

"$SCRIPT_DIR/stop-menubar.sh"
rm -f "$PLIST_PATH"

echo "Removed IdeaForge menu bar LaunchAgent."