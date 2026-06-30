#!/bin/bash
# Wrapper for launchd — runs IdeaForge menu bar status app
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

ROOT="$(ideaforge_project_root)"
cd "$ROOT"

VENV_PYTHON="$ROOT/venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "IdeaForge venv not found. Run ./scripts/install-menubar.sh first." >&2
  exit 127
fi

exec "$VENV_PYTHON" -m ideaforge.menubar_app "$@"