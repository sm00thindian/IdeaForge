# IdeaForge

**Plug in your recorder. Get meeting notes.**

IdeaForge is a local-first pipeline for USB voice recorders (Z28/Z29 and similar). It copies recordings off the device, transcribes them on your Mac, optionally labels who said what, and produces structured meeting notes with action items — powered by Grok or local Ollama.

## How it works

```
USB recorder plugged in
        │
        ▼
┌───────────────────┐
│  Daemon detects   │  polls /Volumes every 5s (or run manually)
│  device mount     │
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  Copy to archive  │  ~/IdeaForge/YYYY-MM-DD/  (SHA-256 dedup)
│  Verify + purge   │  optional: delete from device after verified copy
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  Transcribe       │  mlx-whisper on Apple Silicon (~1 min / 40 min audio)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  Diarize          │  pyannote speaker labels [SPEAKER_00], etc. (optional)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│  Summarize        │  Grok infers names, action items, decisions
└─────────┬─────────┘
          ▼
   summary.md + summary.json
```

**Two ways to run:**

| Mode | Command | Best for |
|------|---------|----------|
| **Daemon** (recommended) | `./scripts/install-daemon.sh` | Hands-off — plug in and walk away |
| **Manual** | `ideaforge --auto-source` | One-off runs, testing, re-processing |

## Features

| Stage | What it does |
|-------|-------------|
| **Detect** | Auto-finds Z28/Z29 recorders under `/Volumes` by `RECORD/` folder + `R*.WAV` pattern |
| **Ingest** | Copies to dated archive with SHA-256 dedup; skips files already processed |
| **Purge** | Daemon removes recordings from device after hash-verified local copy |
| **Transcribe** | mlx-whisper on Apple Silicon (auto), faster-whisper fallback elsewhere |
| **Diarize** | pyannote speaker labels — runs on existing transcript, no re-transcription |
| **Summarize** | Grok (auto when `XAI_API_KEY` set) or Ollama — structured JSON + Markdown |
| **Speakers** | Grok infers real names/roles from conversation; no manual mapping required |

### Processing modes

- **`meeting`** — Executive summary, speaker identities, action items, decisions, follow-ups
- **`creative`** — Song ideas, lyrics drafts, Suno v5.5 prompts
- **`auto`** — LLM classifies transcript and picks the right schema

## Quick start

### 1. Install

```bash
git clone https://github.com/sm00thindian/IdeaForge.git
cd IdeaForge
python3 -m venv venv
source venv/bin/activate
pip install -e ".[all]"
```

Or with `requirements.txt` for a minimal install:

```bash
pip install -r requirements.txt
pip install mlx-whisper pyannote.audio torch   # Apple Silicon + diarization
```

### 2. Secrets

Create a `.env` file in the project root (or set environment variables):

```bash
XAI_API_KEY=xai-...          # Grok meeting notes (recommended)
HF_TOKEN=hf_...                # pyannote diarization (requires HuggingFace license)
```

Accept the pyannote model license at [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) before using diarization.

### 3. Configure

```bash
mkdir -p ~/.config/ideaforge
cp config.toml.example ~/.config/ideaforge/config.toml
```

Key settings:

```toml
[processing]
diarize = true              # enable speaker labels in full pipeline

[diarization]
min_speakers = 2
max_speakers = 6

[daemon]
poll_interval_seconds = 5
settle_seconds = 5          # wait after USB mount before reading files
delete_after_copy = true    # remove recordings from device after verified copy
```

### 4. Your recorder

Z28/Z29 devices mount as exFAT volumes (often `NO NAME` on macOS):

```
/Volumes/NO NAME/
├── RECORD/
│   └── R2026-06-27-07-43-11.WAV   # 12 kHz mono PCM
└── recset.txt
```

### 5. Run

**Daemon (set and forget):**

```bash
./scripts/install-daemon.sh
tail -f ~/Library/Logs/ideaforge/daemon.log
```

Plug in the recorder — IdeaForge copies, transcribes, diarizes, summarizes, and clears the device.

**Manual (one-shot):**

```bash
ideaforge --auto-source
ideaforge --detect                    # list attached recorders
ideaforge --auto-source --list-only   # preview files without processing
```

## Daemon

The daemon watches `/Volumes` and runs the full pipeline when exactly one recorder is detected.

```bash
# Install as macOS LaunchAgent (starts at login, restarts on crash)
./scripts/install-daemon.sh

# Foreground (good for debugging)
ideaforge --daemon

# Restart after code or config changes
launchctl kickstart -k gui/$(id -u)/com.ideaforge.daemon

# Watch logs
tail -f ~/Library/Logs/ideaforge/daemon.log

# Uninstall
./scripts/uninstall-daemon.sh
```

**What happens on plug-in:**

1. Device detected → wait `settle_seconds` for mount to stabilize
2. Copy new recordings to `~/IdeaForge/YYYY-MM-DD/`
3. Hash-verify archive copy → delete from device (if `delete_after_copy = true`)
4. Transcribe → diarize → Grok meeting notes
5. Skip files already in `.processed_log.json` (SHA-256 dedup)

Manual `ideaforge --auto-source` runs do **not** delete device files — only the daemon does.

## Speaker names

Transcripts use pyannote labels: `[SPEAKER_00]`, `[SPEAKER_01]`, etc.

Grok analyzes the conversation and infers who each speaker is — from self-introductions, direct address, and context. Results appear in meeting notes as:

```json
"speaker_identities": [
  {
    "speaker_id": "SPEAKER_00",
    "inferred_name": "Alex",
    "confidence": "high",
    "rationale": "Said 'I'm Alex' at the start"
  }
]
```

Inferred names are used in action items, decisions, and speaker contributions — not raw `SPEAKER_XX` labels.

Optional: override labels in the saved transcript with `[speakers.map]` in `config.toml` if you already know who is who.

## Pipeline stages

Run the full pipeline or individual stages:

```bash
# Full pipeline (default)
ideaforge --auto-source

# Re-run Grok only (~10 seconds)
ideaforge --source ~/IdeaForge/2026-06-27 --llm-only --force

# Diarize without re-transcribing (~25 min CPU; uses cached _turns.json on re-run)
ideaforge --source ~/IdeaForge/2026-06-27 --diarize-only --no-copy

# Transcribe only (fast mlx pass)
ideaforge --auto-source --transcribe-only
```

| Flag | Pipeline |
|------|----------|
| *(default)* | copy → transcribe → diarize* → llm |
| `--transcribe-only` | copy → transcribe |
| `--diarize-only` | diarize → llm |
| `--llm-only` | llm |
| `--no-llm` | skip summarization |
| `--no-copy` | process in-place on device/archive folder |
| `--force` | reprocess even if outputs exist |

\*Diarize runs when `diarize = true` in config or `--diarize` flag is set.

## CLI reference

```
ideaforge [--source PATH | --auto-source | --daemon] [options]

Source:
  --source PATH       Mounted recorder or folder
  --auto-source       Auto-detect USB recorder under /Volumes
  --daemon            Watch for recorder plug-in (foreground)
  --detect            List detected recorders and exit

Pipeline:
  --transcribe-only   Copy + transcribe only
  --diarize-only      Diarize existing transcript
  --llm-only          Re-summarize existing transcript
  --no-copy           Skip copying to archive
  --no-llm            Skip LLM summarization
  --force             Reprocess even if outputs exist

Transcription:
  --whisper-backend   auto | mlx | faster
  --whisper-model     tiny | base | small | medium | large-v3
  --diarize           Enable speaker diarization
  --min-speakers      pyannote hint (e.g. 2)
  --max-speakers      pyannote hint (e.g. 6)

LLM:
  --llm-backend       auto | ollama | grok
  --grok-model        Default: grok-4.3
  --mode              meeting | creative | auto
  --output-format     md | json | both

Daemon:
  --daemon-interval   Poll interval in seconds (default: 5)
  --daemon-settle     Seconds to wait after mount (default: 5)

Config:
  --archive           Archive root (default: ~/IdeaForge)
  --config            Path to config.toml
```

## Output structure

After processing `R2026-06-27-07-43-11.WAV`:

```
~/IdeaForge/2026-06-27/
├── R2026-06-27-07-43-11.WAV              # archived audio
├── R2026-06-27-07-43-11.txt              # transcript ([SPEAKER_XX] if diarized)
├── R2026-06-27-07-43-11_whisper.json     # transcription metadata
├── R2026-06-27-07-43-11_segments.json    # timestamped segments (for --diarize-only)
├── R2026-06-27-07-43-11_turns.json       # cached pyannote turns
├── R2026-06-27-07-43-11_diarized.json    # speaker-labeled segments
├── R2026-06-27-07-43-11_summary.md       # formatted meeting notes
└── R2026-06-27-07-43-11_summary.json     # structured data
```

### Meeting JSON (excerpt)

```json
{
  "title": "Q2 Planning Sync",
  "meeting_type": "planning",
  "executive_summary": "...",
  "speaker_identities": [
    {
      "speaker_id": "SPEAKER_00",
      "inferred_name": "Alex",
      "confidence": "high",
      "rationale": "Introduced themselves at the start"
    }
  ],
  "speakers": [
    {"speaker": "Alex (SPEAKER_00)", "summary": "...", "key_quotes": ["..."]}
  ],
  "action_items": [
    {
      "who": "Alex",
      "what": "Send deck",
      "when": "Friday",
      "priority": "high",
      "confidence": "explicit",
      "source_quote": "I'll send the deck Friday"
    }
  ],
  "decisions": [{"decision": "Delay launch", "rationale": "...", "made_by": "Alex"}],
  "follow_ups": [{"topic": "Capacity", "owner": "Alex", "by_when": "next week"}],
  "metadata": {"llm_backend": "grok", "llm_model": "grok-4.3"}
}
```

## LLM backends

**Auto (default)** — uses Grok when `XAI_API_KEY` is set; otherwise Ollama:

```bash
export XAI_API_KEY="your-key"
ideaforge --auto-source
```

**Ollama only (fully local):**

```bash
ollama pull llama3.1
ideaforge --auto-source --llm-backend ollama
```

Grok is recommended for meeting notes. If a Grok call fails, IdeaForge automatically retries with Ollama.

## Transcription

**Apple Silicon** — mlx-whisper is auto-selected (~1 min per 40 min of audio with `small` model):

```bash
pip install mlx-whisper scipy
ideaforge --auto-source
```

**Other platforms** — falls back to faster-whisper on CPU.

Audio is loaded without ffmpeg (numpy/scipy WAV reader) for reliability.

## Speaker diarization

Diarization runs **after** transcription via pyannote — speaker labels are applied to the existing transcript, not a second transcription pass.

```bash
pip install pyannote.audio torch
export HF_TOKEN="hf_..."
```

Enable in config (`diarize = true`) or per-run (`--diarize`). Tune speaker count hints:

```bash
ideaforge --auto-source --min-speakers 2 --max-speakers 6
```

Cached `_turns.json` and `_segments.json` make re-runs fast — use `--diarize-only` to re-label without re-transcribing.

## Architecture

```
ideaforge/
├── cli.py          # CLI entry point
├── daemon.py       # USB watcher — plug-and-process
├── runner.py       # Pipeline execution (shared by CLI and daemon)
├── pipeline.py     # Stage resolution (--llm-only, etc.)
├── ingest.py       # Copy, dedup, device purge
├── device.py       # Z28/Z29 detection
├── transcribe.py   # mlx-whisper / faster-whisper orchestration
├── diarize.py      # pyannote speaker labeling
├── speakers.py     # Speaker map formatting
├── audio_util.py   # ffmpeg-free audio loader
├── llm.py          # Grok / Ollama backends
├── prompts.py      # Meeting and creative prompts
├── schema.py       # MeetingNotes, SpeakerIdentity, etc.
└── config.py       # TOML + .env loading

scripts/
├── install-daemon.sh    # macOS LaunchAgent installer
├── run-daemon.sh        # Daemon wrapper (loads .env)
└── uninstall-daemon.sh
```

## Privacy

- **Local by default** — audio and transcripts stay on your machine
- **Grok is opt-in** — only used when `XAI_API_KEY` is set (auto backend picks it up)
- **No telemetry** — no analytics, no cloud storage
- **Dedup log** — `~/IdeaForge/.processed_log.json` tracks file hashes locally

## Roadmap

- [ ] Creative mode refinements (chord progression hints, melody notation)
- [ ] MPS acceleration for pyannote diarization
- [x] Watch folder / launchd automation for plug-and-process
- [ ] Export action items to Apple Reminders / Obsidian

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).