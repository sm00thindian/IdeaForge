#!/bin/bash
# Wrapper for launchd — loads .env then runs ideaforge --daemon
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

ROOT="$(ideaforge_project_root)"
cd "$ROOT"

for env_file in "$ROOT/.env" "$HOME/.config/ideaforge/.env"; do
  load_env_file_preserve_existing "$env_file"
done

IDEAFORGE_BIN="$(resolve_ideaforge_bin "$ROOT" || true)"
if [[ -z "$IDEAFORGE_BIN" ]]; then
  echo "ideaforge not found. Run ./scripts/install-daemon.sh to set up the venv." >&2
  exit 127
fi

# Rotate daemon logs when they exceed 10 MiB (keeps .log.1 … .log.3)
PYTHON_BIN="$(dirname "$IDEAFORGE_BIN")/python"
if [[ -x "$PYTHON_BIN" ]]; then
  "$PYTHON_BIN" -c "from ideaforge.log_util import rotate_daemon_logs; rotate_daemon_logs()" 2>/dev/null || true
fi

exec "$IDEAFORGE_BIN" --daemon "$@"