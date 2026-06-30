# Contributing to IdeaForge

Thanks for helping build a privacy-focused voice pipeline. IdeaForge is designed to stay local-first — please keep that principle in mind when proposing changes.

## Development setup

```bash
git clone https://github.com/sm00thindian/IdeaForge.git
cd IdeaForge
python3 -m venv venv
source venv/bin/activate
pip install -e ".[all,dev]"
```

Minimal install (core + tests only):

```bash
pip install -e ".[dev]"
```

Optional stacks are extras in `pyproject.toml`: `mlx`, `diarize`, `claude`, `menubar`, `all`.

For diarization, accept the pyannote license and set `HF_TOKEN`:

```bash
export HF_TOKEN="hf_..."
```

## Project structure

| Module | Responsibility |
|--------|---------------|
| `ideaforge/cli.py` | CLI entry point |
| `ideaforge/daemon.py` | USB watcher, LaunchAgent integration |
| `ideaforge/runner.py` | Pipeline orchestration |
| `ideaforge/session_worker.py` | Per-session pipeline worker |
| `ideaforge/session_pool.py` | Parallel session pool |
| `ideaforge/state_db.py` | Versioned `.processed_log.json` |
| `ideaforge/device_profiles.py` | Z28 / generic_wav device adapters |
| `ideaforge/device_registry.py` | `[[devices]]` binding and archive roots |
| `ideaforge/archive_status.py` | Per-device failure aggregation for status/menubar |
| `ideaforge/fleet.py` | Fleet dashboard TUI and web serve |
| `ideaforge/remote_sync.py` | Optional rsync after meeting notes |
| `ideaforge/speaker_library.py` | Cross-session speaker embedding reuse |
| `ideaforge/session_time.py` | Recording date resolution (recset > filename > mtime) |
| `ideaforge/pipeline.py` | Stage flags (`--llm-only`, etc.) |
| `ideaforge/ingest.py` | File discovery, dedup, archive copy, purge |
| `ideaforge/chunks.py` | Recorder chunk detection and merge rules |
| `ideaforge/device.py` | Z28/Z29 USB detection |
| `ideaforge/transcribe.py` | mlx-whisper / faster-whisper |
| `ideaforge/diarize.py` | pyannote speaker labeling |
| `ideaforge/gpu_lock.py` | Serialize GPU-heavy stages |
| `ideaforge/status.py` | `status.json` for menu bar progress |
| `ideaforge/menubar_app.py` | macOS menu bar UI |
| `ideaforge/llm.py` | Grok / Claude / Ollama backends |
| `ideaforge/config.py` | TOML + `.env` loading |

## Guidelines

- **Modularity** — keep stages independent; each should be skippable via CLI flags
- **Graceful degradation** — optional deps (mlx, pyannote, anthropic) must fail with clear messages, not import-time crashes
- **Privacy** — no network calls unless the user explicitly opts into Grok/Claude or Hugging Face model downloads
- **Tests** — run `python -m pytest`; add tests for ingest, chunks, config, and pipeline behavior
- **Device abstraction** — new recorder support should go through device profiles (see [ROADMAP.md](ROADMAP.md)), not one-off conditionals in ingest

## Testing

```bash
python -m pytest -q -m "not gpu"
```

CI runs on Python 3.10–3.12 (see `.github/workflows/ci.yml`). GPU/diarization tests may skip when torch/pyannote are not installed.

## Testing against a real device

```bash
ideaforge --detect
ideaforge --auto-source --list-only
ideaforge --auto-source --no-llm          # copy + transcribe only
ideaforge --auto-source --no-copy --no-llm  # list from device in-place
```

## Pull requests

1. Fork and create a feature branch
2. Keep changes focused — one feature or fix per PR
3. Update README and CHANGELOG if user-facing behavior changes
4. Ensure `ideaforge --help` works without optional deps installed