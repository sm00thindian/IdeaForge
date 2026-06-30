#!/bin/bash
# Record IdeaForge as a trusted folder for Grok project hooks/MCP/LSP.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GROK_HOME="${GROK_HOME:-$HOME/.grok}"
TRUST_FILE="$GROK_HOME/trusted_folders.toml"
STAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

mkdir -p "$GROK_HOME"

python3 - "$TRUST_FILE" "$ROOT" "$STAMP" <<'PY'
import sys
from pathlib import Path

trust_file, root, stamp = sys.argv[1:4]
root = str(Path(root).resolve())
lines: list[str] = []
folders: dict[str, dict[str, str]] = {}

if Path(trust_file).is_file():
    for raw in Path(trust_file).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[folders.\"") and line.endswith("\"]"):
            current = line[len("[folders.\""):-2]
            folders[current] = {}
            continue
        if "=" in line and "current" in locals() and current:
            key, value = [part.strip() for part in line.split("=", 1)]
            folders[current][key] = value.strip('"')

folders[root] = {"trusted": "true", "decided_at": stamp}
lines.append(f'decided_at = "{stamp}"')
lines.append("")
lines.append("[folders]")
for path in sorted(folders):
    lines.append(f'[folders."{path}"]')
    lines.append(f'trusted = {folders[path].get("trusted", "true")}')
    lines.append(f'decided_at = "{folders[path].get("decided_at", stamp)}"')
    lines.append("")

Path(trust_file).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
print(trust_file)
PY

if command -v grok >/dev/null 2>&1; then
  grok inspect --cwd "$ROOT" 2>/dev/null | rg "Project trusted|Hooks" || true
fi

echo "Trusted IdeaForge for project hooks: $ROOT"