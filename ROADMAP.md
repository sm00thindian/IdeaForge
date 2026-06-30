# IdeaForge roadmap

Prioritized work after **0.5.0**. Items are grouped by tier (impact vs effort) and aligned with long-term goals: reliability on one recorder today, clean extension to multiple devices and vendors tomorrow.

## Principles

1. **Local-first** — USB copy, on-device ML, optional cloud LLM; no required SaaS.
2. **Device-agnostic core** — Ingest, chunking, and pipeline logic should not assume Z28/Z29 filenames; device quirks live in adapters.
3. **Observable** — Logs, `status.json`, and menu bar should answer “what is it doing?” without reading Python tracebacks.
4. **Safe defaults** — Conservative merge rules, serialized GPU by default, explicit opt-in for parallelism.

---

## Tier 1 — Foundation (0.5.x, immediate follow-ups)

| Item | Status | Notes |
|------|--------|-------|
| CHANGELOG + version 0.5.0 | Done in 0.5.0 | Keep updated per release |
| README (menubar, parallel, troubleshooting) | Done in 0.5.0 | |
| GitHub Actions CI (`pytest` on push/PR) | Done in 0.5.0 | |
| Commit & tag release | 0.5.0 | |
| `CONTRIBUTING.md` sync with actual stack | Done in 0.5.0 | |
| Packaging: `numpy`, `rumps` in extras | Done in 0.5.0 | |

### 0.5.1 patch targets

- [x] **Per-session failure isolation** — One bad WAV should not block the executor; mark failed and continue.
- [x] **Menubar “Open log”** — Menu item opens `~/Library/Logs/ideaforge/daemon.log`.
- [x] **Status: diarization sub-progress** — Duration hint + segment labeling progress in `status.json`.
- [x] **Daemon ingest-first** — Copy → verify → delete → unmount, then process from archive.

### 0.5.2 patch targets

- [x] **Failed session state** — Persist failures in `.processed_log.json`; auto-retry on next run; `--retry-failed` for manual retry.
- [x] **Ingest-only dry run** — `ideaforge --ingest-only` for testing copy/verify/unmount without ML.

### 0.5.3 patch targets

- [x] **`ideaforge --status`** — Print `status.json`, daemon/menubar health, pending failure count.
- [x] **Failure notification** — macOS alert when a session fails (`notify_on_failure` config).

### 0.5.4 patch targets

- [ ] **Menubar “Open Log” opens Terminal tail** — `tail -f` in Terminal.app instead of log file in editor.
- [ ] **Status watch mode** — `ideaforge --status --watch` refreshes every N seconds.

---

## Tier 2 — Operator experience (0.6.0)

| Item | Rationale |
|------|-----------|
| **`ideaforge reprocess`** | CLI to re-run pipeline for a session dir or date range without hand-editing state DB |
| **`ideaforge status`** | Print current `status.json` + daemon/menubar health (pgrep, lock files) |
| **Recorder clock helper** | `ideaforge device clock` — read `recset.txt`, show skew vs system time, optional doc for fixing device date |
| **Config validation** | Fail fast on unknown keys / bad paths at daemon start |
| **Archive layout docs** | Document `sessions/`, `chunks/`, `notes/` tree in README |
| **LaunchAgent reload note** | Single doc section: when to `launchctl kickstart` after config/env changes |

### Tech debt (0.6.0)

- [ ] **Centralize stage constants** — `status.py` stage strings used in runner/transcribe/diarize/llm; single enum or module.
- [ ] **State DB migrations** — Version schema; avoid silent breakage when adding columns.
- [ ] **Reduce `runner.py` surface** — Extract session worker + pool into `pipeline.py` or `session_worker.py`.
- [ ] **Type hints pass** — `config.py`, `ingest.py`, `chunks.py` for mypy-ready subset.
- [ ] **Log rotation** — `daemon.log` growth; newsyslog or built-in rotate.

---

## Tier 3 — Quality & scale (0.7.0+)

| Item | Rationale |
|------|-----------|
| **E2E smoke test** | Fixture WAV → mock LLM → assert `notes.md` exists (CI without GPU optional job) |
| **GPU CI job (optional)** | Self-hosted macOS runner or manual `workflow_dispatch` for transcribe/diarize |
| **Integration test: multi-chunk merge** | Regression for `concat_wav_files` + `chunks_are_continuation` |
| **Performance baselines** | Document RTF (real-time factor) per stage on M-series for planning |

---

## Multi-recorder / multi-device strategy (0.8.0+)

Goal: support different USB recorders (Z28, Z29, generic MSC, future vendors) without forking ingest logic.

### Phase A — Device profile config (0.8.0)

```toml
[[devices]]
name = "office-z28"
mount_glob = "NO NAME"          # or volume label / path prefix
profile = "z28"

[[devices]]
name = "field-recorder"
mount_glob = "RECORDER"
profile = "generic_wav"
```

- [ ] **`DeviceProfile` protocol** — `discover_files()`, `parse_session_id()`, `read_device_clock()`, `stable_file_predicate()`.
- [ ] **Built-in profiles** — `z28` (current `RECORD/R*.WAV` + `recset.txt`), `generic_wav` (recursive `.wav` by mtime).
- [ ] **Per-device archive subdir** — `~/IdeaForge/{device_name}/sessions/...` to avoid collisions.
- [ ] **Daemon: multi-volume** — Already watches `/Volumes/*`; map volume → profile via config.

### Phase B — Heterogeneous formats (0.9.0)

- [ ] **MP3/FLAC ingest** — Normalize to WAV via ffmpeg before transcribe (config flag).
- [ ] **Non-segmented recorders** — Single long file per day; chunk by silence or fixed window instead of filename gaps.
- [ ] **Clock skew policy** — Prefer device `recset.txt` when present, else filename, else mtime; document in notes frontmatter.

### Phase C — Fleet ops (1.0.0)

- [ ] **Web or TUI dashboard** — Optional; read-only view of `status.json` + queue across devices.
- [ ] **Remote archive sync** — rsync/NAS hook after notes generated (not in core).
- [ ] **Speaker library** — Reuse embeddings across sessions (pyannote/custom).

---

## Explicit non-goals (for now)

- Windows/Linux daemon parity (macOS LaunchAgent is the reference).
- Real-time streaming transcription while recording.
- Replacing ffmpeg/torch stack with cloud ASR.
- Mobile app.

---

## How to use this doc

- Pick the next milestone (e.g. 0.5.1) from Tier 1 unfinished + Tier 2 small wins.
- Open a GitHub issue per checkbox; link PRs in CHANGELOG.
- Revisit **Multi-recorder** before adding a second physical device to production.

See [CHANGELOG.md](CHANGELOG.md) for shipped work.