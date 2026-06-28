# Session continuity

At the **start** of every IdeaForge coding session:

1. Read `.last-grok-session.json` if it exists.
2. Resume context from `session_path` (Grok transcript) when the user's request depends on prior work.
3. Mention the saved `title` and any `next_steps` when they are relevant.

Before ending a session (or when the user says they are done for now):

1. Run `./scripts/save-grok-session.sh` (or `python scripts/save_grok_session.py`).
2. Update `next_steps` with concrete follow-ups using `--next-step` flags when useful.
3. Add a short `--note` if there is important state that is not obvious from git history.

Resume commands for the user:

```bash
grok --resume <session_id>    # from .last-grok-session.json
grok -c                       # continue most recent session in this repo
```

The snapshot file is gitignored — it is local developer state only.