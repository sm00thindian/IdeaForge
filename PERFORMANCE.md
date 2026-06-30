# IdeaForge performance baselines

Rough **real-time factor (RTF)** — wall-clock seconds per second of audio (or per session minute) — for planning batch runs on Apple Silicon. These are indicative, not benchmarks; measure on your hardware before sizing parallel sessions.

**RTF < 1.0** means faster than real time (e.g. 0.025 ≈ 40× realtime).

## Apple Silicon (M-series, reference)

| Stage | Typical RTF | Notes |
|-------|-------------|--------|
| **Ingest** (copy + SHA-256) | ~0.001–0.01 | Dominated by USB speed and file size; negligible vs ML. |
| **Chunk merge** (`concat_wav_files`) | ~0.001 | In-memory PCM concat for same-format WAVs. |
| **Transcribe** (mlx-whisper `small`) | ~0.025 | ~1 min wall per 40 min audio (README reference). Scales with model: `tiny` faster, `large-v3` slower. |
| **Diarize** (pyannote) | ~0.3–1.5+ | Highly length-dependent; 60+ min sessions can take tens of minutes on GPU. |
| **Summarize** (Grok / Claude API) | N/A (per session) | Network + token count; often 10–60 s per meeting, overlaps when `max_parallel_sessions > 1`. |
| **Summarize** (Ollama local) | N/A | Depends on model and context length. |

## Daemon end-to-end (plug-in → notes)

For a **single 40 min meeting** (one session, no diarize, Grok summarize):

1. Clock sync + ingest + unmount — seconds
2. Transcribe — ~1 min
3. LLM — ~15–45 s

**Total hands-off:** roughly **2–3 min** after mount settles, excluding queue time when multiple sessions backlog.

## Parallel sessions

With `max_parallel_sessions = 2`:

- Transcribe and diarize share a **GPU lock** — only one heavy job at a time.
- LLM calls can overlap with the next session's transcribe.
- Expect diminishing returns beyond 2 on a single Mac unless summarize dominates and APIs are fast.

## How to measure locally

```bash
# Time a single archived session reprocess (no copy)
time ideaforge --reprocess --source ~/IdeaForge/YYYY-MM-DD --session R... --no-llm

# Watch live stage timing in menu bar / status.json
ideaforge --status --watch
```

Record audio duration from `*_whisper.json` (`duration_seconds`) and compare to wall time from logs.

## CI vs production

- **GitHub Actions (Ubuntu):** pytest only — no mlx/pyannote GPU path. See E2E smoke test with mocked ML.
- **GPU smoke (manual):** `.github/workflows/gpu-smoke.yml` on a self-hosted or `workflow_dispatch` macOS runner with `IDEAFORGE_GPU_CI=1`.

Update this doc when you change default whisper model or add ffmpeg-normalized ingest.