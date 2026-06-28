#!/bin/bash
# Grok/Cursor hook wrapper — writes .last-grok-session.json on session end.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${ROOT}/venv/bin/python3"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

exec "$PYTHON" "$SCRIPT_DIR/save_grok_session.py" "$@"