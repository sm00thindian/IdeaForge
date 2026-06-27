#!/bin/bash
# Shared helpers for IdeaForge daemon scripts

ideaforge_project_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  (cd "$script_dir/.." && pwd)
}

resolve_ideaforge_bin() {
  local root="$1"
  local candidate=""

  for candidate in \
    "${IDEAFORGE_BIN_OVERRIDE:-}" \
    "$root/venv/bin/ideaforge" \
    "$(command -v ideaforge 2>/dev/null || true)" \
    "$HOME/.local/bin/ideaforge" \
    "/opt/homebrew/bin/ideaforge"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_ideaforge_venv() {
  local root="$1"
  local venv="$root/venv"
  local python="${PYTHON:-python3}"

  if [[ -x "$venv/bin/ideaforge" ]]; then
    return 0
  fi

  echo "Setting up IdeaForge virtualenv at $venv"

  if [[ ! -d "$venv" ]]; then
    if ! command -v "$python" >/dev/null 2>&1; then
      echo "python3 not found — install Python 3.10+ first." >&2
      return 1
    fi
    "$python" -m venv "$venv"
  fi

  # shellcheck disable=SC1091
  source "$venv/bin/activate"
  python -m pip install --upgrade pip
  pip install -e "$root/.[all]"

  if [[ ! -x "$venv/bin/ideaforge" ]]; then
    echo "ideaforge not found in venv after install." >&2
    return 1
  fi

  echo "Installed IdeaForge into venv: $venv/bin/ideaforge"
}