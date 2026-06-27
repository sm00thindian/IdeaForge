#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

LABEL="com.ideaforge.daemon"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

unload_launch_agent "$PLIST_PATH" "$LABEL"
rm -f "$PLIST_PATH"

echo "IdeaForge daemon removed."