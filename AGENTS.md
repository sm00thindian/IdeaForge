# IdeaForge agent notes

## Project

Local-first USB voice recorder pipeline: copy → transcribe → diarize → Grok/Claude/Ollama meeting notes. macOS daemon watches `/Volumes`.

## Conventions

- Python 3.10+, `pip install -e ".[all]"` in project `venv/`
- Config: `~/.config/ideaforge/config.toml` (see `config.toml.example`)
- Secrets: shell env or `.env`; reinstall daemon after key changes (`./scripts/install-daemon.sh`)
- Tests: `python -m pytest`

## Session continuity

Read `.last-grok-session.json` at the start of a session to pick up prior Grok work. Before stopping, run:

```bash
./scripts/save-grok-session.sh
```

Add follow-ups with `--next-step "..."` and optional `--note "..."`. See `.grok/rules/session-continuity.md`.