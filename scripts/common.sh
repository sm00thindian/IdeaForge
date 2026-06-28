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

strip_env_value() {
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
      -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

read_secret_from_file() {
  local key="$1"
  local env_file="$2"
  local value=""

  if [[ ! -f "$env_file" ]]; then
    return 1
  fi

  value="$(
    grep -E "^${key}=" "$env_file" 2>/dev/null | head -1 | cut -d= -f2- | strip_env_value
  )"
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
    return 0
  fi
  return 1
}

# Shell env > project .env > ~/.config/ideaforge/.env
resolve_secret() {
  local key="$1"
  local root="$2"
  local value=""
  local env_file

  value="${!key:-}"
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
    return 0
  fi

  for env_file in "$root/.env" "$HOME/.config/ideaforge/.env"; do
    if value="$(read_secret_from_file "$key" "$env_file")"; then
      printf '%s' "$value"
      return 0
    fi
  done
  return 1
}

secret_source_label() {
  local key="$1"
  local root="$2"
  local env_file

  if [[ -n "${!key:-}" ]]; then
    printf 'shell environment'
    return 0
  fi
  for env_file in "$root/.env" "$HOME/.config/ideaforge/.env"; do
    if read_secret_from_file "$key" "$env_file" >/dev/null; then
      printf '%s' "$env_file"
      return 0
    fi
  done
  return 1
}

plist_env_xml_for_secrets() {
  local root="$1"
  local key value

  for key in XAI_API_KEY HF_TOKEN ANTHROPIC_API_KEY; do
    if value="$(resolve_secret "$key" "$root")"; then
      printf '        <key>%s</key>\n        <string>%s</string>\n' "$key" "$value"
    fi
  done
}

load_env_file_preserve_existing() {
  local env_file="$1"
  local line key value

  if [[ ! -f "$env_file" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      value="${BASH_REMATCH[2]}"
      value="$(printf '%s' "$value" | strip_env_value)"
      if [[ -z "${!key:-}" && -n "$value" ]]; then
        export "$key=$value"
      fi
    fi
  done < "$env_file"
}

check_daemon_secrets() {
  local root="$1"
  local missing=0
  local source

  if resolve_secret "XAI_API_KEY" "$root" >/dev/null; then
    source="$(secret_source_label "XAI_API_KEY" "$root")"
    echo "✓ XAI_API_KEY found ($source)"
  else
    echo "⚠️  XAI_API_KEY not found — Grok will not work (falls back to Ollama)"
    echo "   Export it in your shell or add to $root/.env, then run ./scripts/install-daemon.sh"
    missing=1
  fi

  if resolve_secret "HF_TOKEN" "$root" >/dev/null; then
    source="$(secret_source_label "HF_TOKEN" "$root")"
    echo "✓ HF_TOKEN found ($source)"
  else
    echo "⚠️  HF_TOKEN not found — diarization may fail"
    echo "   Export it in your shell or add to $root/.env, then run ./scripts/install-daemon.sh"
    missing=1
  fi

  return "$missing"
}

launch_agent_domain() {
  printf 'gui/%s' "$(id -u)"
}

unload_launch_agent() {
  local plist="$1"
  local label="$2"
  local domain
  domain="$(launch_agent_domain)"

  launchctl bootout "$domain/$label" 2>/dev/null || true
  launchctl bootout "$domain" "$plist" 2>/dev/null || true
  launchctl unload "$plist" 2>/dev/null || true
  launchctl disable "$domain/$label" 2>/dev/null || true
}

load_launch_agent() {
  local plist="$1"
  local label="$2"
  local domain
  domain="$(launch_agent_domain)"

  if [[ ! -f "$plist" ]]; then
    echo "Plist not found: $plist" >&2
    return 1
  fi

  if ! plutil -lint "$plist" >/dev/null 2>&1; then
    echo "Invalid plist: $plist" >&2
    plutil -lint "$plist" >&2
    return 1
  fi

  unload_launch_agent "$plist" "$label"
  sleep 0.5

  # bootstrap fails on some macOS versions (e.g. 26.x) — fall back to load
  if launchctl bootstrap "$domain" "$plist" 2>/dev/null; then
    launchctl enable "$domain/$label" 2>/dev/null || true
  elif launchctl load -w "$plist" 2>/dev/null; then
    echo "Loaded via launchctl load (bootstrap unavailable on this macOS version)."
  else
    echo "Failed to load LaunchAgent." >&2
    return 1
  fi

  launchctl kickstart -k "$domain/$label" 2>/dev/null || true
  return 0
}