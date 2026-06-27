# Contributing to IdeaForge

Thanks for helping build a privacy-focused voice pipeline. IdeaForge is designed to stay local-first — please keep that principle in mind when proposing changes.

## Development setup

```bash
git clone https://github.com/yourusername/IdeaForge.git
cd IdeaForge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Optional diarization stack:

```bash
pip install whisperx
export HF_TOKEN="hf_..."
```

## Project structure

| Module | Responsibility |
|--------|---------------|
| `ideaforge/cli.py` | CLI and pipeline orchestration |
| `ideaforge/ingest.py` | File discovery, dedup, archive copy |
| `ideaforge/device.py` | USB recorder detection |
| `ideaforge/transcribe.py` | Whisper transcription + diarization |
| `ideaforge/llm.py` | LLM backends and structured output |
| `ideaforge/prompts.py` | Prompt templates per mode |
| `ideaforge/schema.py` | Output dataclasses (JSON + Markdown) |
| `ideaforge/config.py` | TOML configuration |

## Guidelines

- **Modularity** — keep stages independent; each should be skippable via CLI flags
- **Graceful degradation** — optional deps (whisperx, ollama, openai) must fail with clear messages, not import-time crashes
- **Privacy** — no network calls unless the user explicitly opts into Grok or diarization model downloads
- **Tests** — add tests for ingest hashing, device detection heuristics, JSON parsing, and schema rendering

## Testing against a real device

```bash
python ideaforge.py --detect
python ideaforge.py --auto-source --list-only
python ideaforge.py --auto-source --no-llm          # copy + transcribe only
python ideaforge.py --auto-source --no-copy --no-llm  # list from device in-place
```

## Pull requests

1. Fork and create a feature branch
2. Keep changes focused — one feature or fix per PR
3. Update README if CLI flags or config options change
4. Ensure `python ideaforge.py --help` still works without optional deps installed