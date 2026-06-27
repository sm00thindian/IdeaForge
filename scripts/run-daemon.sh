#!/bin/bash
# Wrapper for launchd — loads .env then runs ideaforge --daemon
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

for env_file in "$ROOT/.env" "$HOME/.config/ideaforge/.env"; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    break
  fi
done

IDEAFORGE_BIN=""
for candidate in \
  "${IDEAFORGE_BIN_OVERRIDE:-}" \
  "$(command -v ideaforge 2>/dev/null || true)" \
  "$ROOT/venv/bin/ideaforge" \
  "$HOME/.local/bin/ideaforge" \
  "/opt/homebrew/bin/ideaforge"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    IDEAFORGE_BIN="$candidate"
    break
  fi
done

if [[ -z "$IDEAFORGE_BIN" ]]; then
  echo "ideaforge not found in PATH or $ROOT/venv/bin" >&2
  exit 127
fi

exec "$IDEAFORGE_BIN" --daemon "$@"