<p align="center">
  <img src="ideaforge/assets/logo.svg" alt="IdeaForge" width="420">
</p>

# IdeaForge

**Plug in your recorder. Get meeting notes.**

IdeaForge is a local-first pipeline for USB voice recorders (Z28/Z29 and similar). It copies recordings off the device, transcribes them on your Mac, optionally labels who said what, and produces structured meeting notes with action items — powered by **Grok** (default), **Claude** (opt-in), or **Ollama** (fully local).

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
│  Merge chunks     │  consecutive splits → one session (e.g. 15 min max)
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
│  Summarize        │  LLM infers names, action items, decisions
└─────────┬─────────┘
          ▼
   summary.md + summary.json
```

**Two ways to run:**

| Mode | Command | Best for |
|------|---------|----------|
| **Daemon** (recommended) | `./scripts/install-daemon.sh` | Hands-off — plug in and walk away |
| **Manual** | `ideaforge --auto-source` | One-off runs, testing, re-processing |

## Choose your LLM

| Backend | Config | API key | Notes |
|---------|--------|---------|-------|
| **Grok** | `backend = "auto"` or `"grok"` | `XAI_API_KEY` | **Default** — auto-selected when key is set |
| **Claude** | `backend = "claude"` | `ANTHROPIC_API_KEY` | Opt-in — same prompts and JSON output |
| **Ollama** | `backend = "ollama"` | — | Fully local fallback |

`auto` prefers Grok when `XAI_API_KEY` is present; otherwise Ollama. Claude is never auto-selected — set it explicitly.

## Features

| Stage | What it does |
|-------|-------------|
| **Detect** | Auto-finds Z28/Z29 recorders under `/Volumes` by `RECORD/` folder + `R*.WAV` pattern |
| **Ingest** | Copies to dated archive with SHA-256 dedup; merges consecutive recorder chunks into one session |
| **Purge** | Daemon removes recordings from device after hash-verified local copy |
| **Transcribe** | mlx-whisper on Apple Silicon (auto), faster-whisper fallback elsewhere |
| **Diarize** | pyannote speaker labels — runs on existing transcript, no re-transcription |
| **Summarize** | Grok, Claude, or Ollama — structured JSON + Markdown meeting notes |
| **Speakers** | LLM infers real names/roles from conversation; no manual mapping required |

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

Minimal install:

```bash
pip install -r requirements.txt
pip install mlx-whisper scipy          # Apple Silicon transcription
pip install pyannote.audio torch       # speaker diarization
pip install anthropic                  # only if using Claude backend
```

### 2. Secrets

Set API keys in your shell **or** in a `.env` file (project root or `~/.config/ideaforge/.env`):

```bash
# Pick one or both — Grok is used by default when XAI_API_KEY is set
export XAI_API_KEY=xai-...       # Grok (default with backend=auto)
export HF_TOKEN=hf_...           # pyannote diarization
```

Or in `.env`:

```bash
XAI_API_KEY=xai-...
ANTHROPIC_API_KEY=sk-ant-...     # Claude (requires backend=claude)
HF_TOKEN=hf_...
```

**CLI / foreground** (`ideaforge --daemon`) picks up exported shell variables and loads `.env` without overwriting them.

**LaunchAgent daemon** does *not* inherit your login-shell environment. When you run `./scripts/install-daemon.sh`, it snapshots keys from your current shell **or** `.env` into the LaunchAgent plist. If you only export keys in `~/.zshrc`, open a terminal where they are set and reinstall:

```bash
./scripts/install-daemon.sh
```

Accept the pyannote license at [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) before using diarization.

### 3. Configure

```bash
mkdir -p ~/.config/ideaforge
cp config.toml.example ~/.config/ideaforge/config.toml
```

Example for a full hands-off setup (Grok + diarization + daemon purge):

```toml
archive = "~/IdeaForge"

[llm]
backend = "auto"          # Grok when XAI_API_KEY is set
grok_model = "grok-4.3"

[processing]
diarize = true
merge_chunks = true       # join consecutive recorder splits into one session
chunk_gap_seconds = 30    # max gap between chunk end and next start

[diarization]
min_speakers = 2
max_speakers = 6

[daemon]
poll_interval_seconds = 5
settle_seconds = 5
delete_after_copy = true  # remove from device after verified copy
notify = true             # macOS popup when pipeline finishes
```

For Claude instead of Grok:

```toml
[llm]
backend = "claude"
claude_model = "claude-sonnet-4-20250514"
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
./scripts/install-daemon.sh          # creates venv if needed, no manual activate
tail -f ~/Library/Logs/ideaforge/daemon.log
```

Plug in the recorder — IdeaForge copies, transcribes, diarizes, summarizes, and clears the device.

> **Note:** Run `./scripts/install-daemon.sh` before `launchctl kickstart`. The LaunchAgent must be installed first.

**Manual (one-shot):**

```bash
ideaforge --auto-source
ideaforge --detect                    # list attached recorders
ideaforge --auto-source --list-only   # preview files without processing
```

## Daemon

The daemon watches `/Volumes` and runs the full pipeline when exactly one recorder is detected.

Re-run `./scripts/install-daemon.sh` after changing API keys — the installer reads from your shell environment and `.env` files and writes them into the LaunchAgent.

```bash
# Install as macOS LaunchAgent (creates project venv + pip install if needed)
./scripts/install-daemon.sh

# Foreground (good for debugging)
ideaforge --daemon

# Restart after code or config changes
launchctl kickstart -k gui/$(id -u)/com.ideaforge.daemon

# Watch logs
tail -f ~/Library/Logs/ideaforge/daemon.log

# Stop (keeps install — restart with install-daemon.sh)
./scripts/stop-daemon.sh

# Uninstall completely
./scripts/uninstall-daemon.sh
```

**What happens on plug-in:**

1. Device detected → wait `settle_seconds` for mount to stabilize
2. Copy new recordings to `~/IdeaForge/YYYY-MM-DD/`
3. Merge consecutive chunks into one session (when `merge_chunks = true`)
4. Hash-verify archive copy → delete from device (if `delete_after_copy = true`)
5. Transcribe → diarize → LLM meeting notes (Grok by default)
6. Skip sessions already in `.processed_log.json` (SHA-256 dedup per chunk)
7. macOS notification with meeting title and action item summary (`notify = true`)

Notifications use the IdeaForge icon when [terminal-notifier](https://github.com/julienXX/terminal-notifier) is installed (`brew install terminal-notifier`). Without it, macOS falls back to the default Script Editor icon.

Manual `ideaforge --auto-source` runs do **not** delete device files — only the daemon does.

## Speaker names

Transcripts use pyannote labels: `[SPEAKER_00]`, `[SPEAKER_01]`, etc.

The LLM (Grok or Claude) analyzes the conversation and infers who each speaker is — from self-introductions, direct address, and context. Results appear in meeting notes as:

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

# Re-run LLM only (~10 seconds)
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
  --llm-backend       auto | ollama | grok | claude
  --grok-model        Default: grok-4.3
  --claude-model      Default: claude-sonnet-4-20250514
  --ollama-model      Default: llama3.1
  --mode              meeting | creative | auto
  --output-format     md | json | both

Daemon:
  --daemon-interval   Poll interval in seconds (default: 5)
  --daemon-settle     Seconds to wait after mount (default: 5)

Export:
  --export-only       Export from existing *_summary.json (requires --source)
  --export-reminders  Push action items to Apple Reminders (macOS)
  --export-obsidian   Append action items to Obsidian note
  --no-export         Skip action item export this run

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
├── R2026-06-27-07-43-11_merged.WAV       # temporary merge when session has multiple chunks
└── R2026-06-27-07-43-11_summary.json     # structured data
```

**Chunked recordings:** Recorders with a max clip length (e.g. 15 minutes) split long sessions into consecutive `R*.WAV` files. IdeaForge detects chunks whose end-to-start gap is within `chunk_gap_seconds` (default 30s), merges them for transcription/diarization/LLM, and writes one transcript + summary per session (stem = first chunk). Individual chunk files are still archived separately.

```toml
[processing]
merge_chunks = true
chunk_gap_seconds = 30
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

### Grok (default)

```bash
export XAI_API_KEY="your-key"
ideaforge --auto-source                    # auto picks Grok
ideaforge --auto-source --llm-backend grok # explicit
```

### Claude (opt-in)

```bash
pip install anthropic                      # or: pip install -e ".[claude]"
export ANTHROPIC_API_KEY="your-key"
ideaforge --auto-source --llm-backend claude
```

```toml
# ~/.config/ideaforge/config.toml
[llm]
backend = "claude"
claude_model = "claude-sonnet-4-20250514"
```

### Ollama (fully local)

```bash
ollama pull llama3.1
ideaforge --auto-source --llm-backend ollama
```

Grok and Claude fall back to Ollama automatically if the API call fails.

## Export action items

Optionally push action items from meeting notes to **Apple Reminders** (macOS) and/or **Obsidian**. **Both are off by default** — enable only what you use.

```toml
# ~/.config/ideaforge/config.toml
[export]
reminders = false          # opt-in: Apple Reminders (macOS)
reminders_list = "IdeaForge"
obsidian = false           # opt-in: append to Obsidian note
obsidian_vault = "~/Documents/Obsidian/MyVault"
obsidian_note = "IdeaForge/Action Items.md"
```

Exports run automatically after LLM summarization when enabled. Duplicate items are skipped via a fingerprint log at `~/IdeaForge/.action_export_log.json`.

```bash
# Export from existing summaries without re-running the LLM
ideaforge --source ~/IdeaForge/2026-06-27 --export-only --export-reminders --export-obsidian

# One-off flags override config for a single run
ideaforge --source ~/IdeaForge/2026-06-27 --llm-only --export-reminders
ideaforge --auto-source --no-export          # disable export this run
```

**Reminders** — creates tasks in a named list with owner, deadline, priority, and source quote in the notes.

**Obsidian** — appends checkbox tasks with Dataview-friendly `priority::` / `source::` fields and wikilinks back to the recording summary.

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
├── chunks.py       # Detect and group consecutive recorder chunks
├── device.py       # Z28/Z29 detection
├── transcribe.py   # mlx-whisper / faster-whisper orchestration
├── diarize.py      # pyannote speaker labeling
├── speakers.py     # Speaker map formatting
├── audio_util.py   # ffmpeg-free audio loader
├── llm.py          # Grok / Claude / Ollama backends
├── export.py       # Apple Reminders + Obsidian action item export
├── prompts.py      # Meeting and creative prompts
├── schema.py       # MeetingNotes, SpeakerIdentity, etc.
├── config.py       # TOML + .env loading
├── notify.py       # macOS completion notifications
├── branding.py     # Logo/icon asset paths
└── assets/         # logo.svg, icon.png, social-preview.png

scripts/
├── common.sh            # Venv setup + binary resolution
├── install-daemon.sh    # macOS LaunchAgent installer
├── run-daemon.sh        # Daemon wrapper (loads .env without overriding plist env)
├── stop-daemon.sh       # Stop daemon without uninstalling
└── uninstall-daemon.sh
```

## Privacy

- **Local by default** — audio and transcripts stay on your machine
- **Cloud LLMs are opt-in** — Grok (auto default) needs `XAI_API_KEY`; Claude needs `ANTHROPIC_API_KEY` and `backend = "claude"`
- **No telemetry** — no analytics, no cloud storage
- **Dedup log** — `~/IdeaForge/.processed_log.json` tracks file hashes locally

## Grok session continuity

IdeaForge keeps a local, gitignored snapshot at `.last-grok-session.json` so you can resume long Grok/Cursor sessions.

```bash
./scripts/save-grok-session.sh
grok --resume <session_id>   # id from .last-grok-session.json
grok -c                      # continue most recent session in this repo
```

Project hooks in `.grok/hooks/` auto-save on session end. Trust the repo once with `/hooks-trust` (or `grok --trust`) so hooks run. Agents read `AGENTS.md` and `.grok/rules/session-continuity.md` at session start.

## Branding

Logo and icon assets live in `ideaforge/assets/`. For GitHub, set the repository social preview image to `ideaforge/assets/social-preview.png` (Settings → General → Social preview).

Install [terminal-notifier](https://github.com/julienXX/terminal-notifier) (`brew install terminal-notifier`) so daemon notifications show the IdeaForge icon.

## Roadmap

- [ ] Creative mode refinements (chord progression hints, melody notation)
- [ ] MPS acceleration for pyannote diarization
- [x] Watch folder / launchd automation for plug-and-process
- [x] Export action items to Apple Reminders / Obsidian
- [x] Merge chunked recorder sessions before transcribe/summarize
- [x] IdeaForge logo and macOS notification icon

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).