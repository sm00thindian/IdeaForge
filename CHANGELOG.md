# Changelog

All notable changes to IdeaForge are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.1] - 2026-06-30

### Added

- **Per-device status aggregation** — `ideaforge --status` and menubar failure badge read `.processed_log.json` from each `[[devices]]` archive root (`archive_status.py`).

### Changed

- **README** — Documents 0.9.0 processing options, 1.0.0 fleet/sync/speakers, `ffmpeg`/`rsync` deps, and flat→per-device archive coexistence.
- **ROADMAP** — Post-1.0 Tier 1 (done) and Tier 2 (1.1.0) planning.

## [1.0.0] - 2026-06-30

### Added

- **Fleet dashboard** — `ideaforge fleet` shows pipeline state, per-device failures, and pending queues; `fleet --serve` hosts a read-only web UI.
- **Remote archive sync** — `[sync]` config runs rsync after meeting notes are generated (`scope`: session/device/archive).
- **Speaker library** — Reuses pyannote embeddings across sessions; `ideaforge speakers list`; auto-apply/learn via `[speakers]` settings.

## [0.9.0] - 2026-06-30

### Added

- **MP3/FLAC ingest** — `normalize_audio` (default `true`) converts non-WAV sources to PCM WAV via ffmpeg before merge/transcribe/diarize.
- **Non-segmented splitting** — `chunk_mode` (`gap` | `silence` | `fixed_window` | `none`) splits long non-`R*` files into sessions.
- **Clock skew policy** — Archive folders and session dates use `recset.txt` > filename > mtime (`session_time.py`).
- **Summary frontmatter** — `*_summary.md` includes YAML `date` and `recording_date_source` when authoritative dating is known.

## [0.8.0] - 2026-06-30

### Added

- **Device profiles** — `DeviceProfile` protocol with built-in `z28` and `generic_wav` adapters (`device_profiles.py`).
- **`[[devices]]` config** — Map volume `mount_glob` to profile and logical `name`; validated by `--validate-config`.
- **Per-device archive paths** — `~/IdeaForge/{device_name}/YYYY-MM-DD/` when devices are configured.
- **Multi-volume daemon** — Processes multiple configured recorders (one device per poll cycle); legacy single-Z28 mode unchanged without `[[devices]]`.

## [0.7.1] - 2026-06-30

### Added

- **Multi-chunk merge integration test** — `group_recordings` + `chunks_are_continuation` + `concat_wav_files` duration regression.
- **E2E smoke test** — Full copy → transcribe → summarize path with mocked ML; asserts `*_summary.md` / `*.txt` outputs (`pytest -m e2e`).
- **Performance baselines** — [PERFORMANCE.md](PERFORMANCE.md) RTF table for M-series planning.
- **GPU smoke workflow** — Manual `workflow_dispatch` job (`.github/workflows/gpu-smoke.yml`); default CI excludes `gpu`-marked tests.

### Changed

- CI runs `pytest -m "not gpu"` on Ubuntu (Python 3.10–3.12).

## [0.7.0] - 2026-06-30

### Added

- **Versioned state DB** — `state_db.py` versions `.processed_log.json` (`schema_version`); migrates legacy logs on load.
- **Session worker split** — `session_worker.py` (per-session pipeline) and `session_pool.py` (parallel executor); `runner.py` is orchestration only.
- **Daemon log rotation** — `run-daemon.sh` rotates `daemon.log` / `daemon.err.log` at 10 MiB (keeps three backups).
- **Mypy subset** — `[tool.mypy]` config for `config.py`, `chunks.py`, `ingest.py`, `state_db.py`, `log_util.py`.

### Changed

- `Stage` / `StepId` / `StepLabel` constants (from 0.6.2) now used across the refactored session modules.

## [0.6.2] - 2026-06-30

### Changed

- **Centralized stage constants** — `Stage`, `StepId`, and `StepLabel` in `status.py` replace scattered stage strings in daemon, ingest, runner, transcribe, diarize, and llm.

## [0.6.1] - 2026-06-30

### Added

- **Daemon clock sync** — Before ingest, read `recset.txt` and write system time when skew exceeds `clock_skew_threshold_seconds` (default 60s). Runs while the volume is still mounted, before copy/unmount.
- **`ideaforge device clock --sync`** — Manually update `recset.txt` from the CLI (`--force` to always write).
- **Archive layout docs** — README documents the `~/IdeaForge/YYYY-MM-DD/` tree, session stems, chunk merge artifacts, and runtime state paths.
- **LaunchAgent reload guide** — README table for when to `launchctl kickstart` vs re-run `install-daemon.sh` after config, secrets, or code changes.

### Changed

- Daemon and `--ingest-only` call clock sync first when `sync_device_clock = true` (default).
- Troubleshooting and recorder-clock notes aligned with actual archive folder rules (mtime at ingest, filename session stems).

## [0.6.0] - 2026-06-30

### Added

- **`ideaforge device clock`** — Parse `recset.txt`, compare device time to system clock, show skew (`--device-clock` alias).
- **`ideaforge --validate-config`** — Check config.toml for unknown keys and invalid values.
- **Daemon config validation** — LaunchAgent daemon exits immediately on invalid config.

## [0.5.5] - 2026-06-30

### Added

- **`ideaforge --reprocess`** — Re-run pipeline on archived sessions (`--source` date folder or archive root with `--from`/`--to`; optional `--session` filter). Implies `--force`, no copy.
- **Menubar failure badge** — Title shows `⚠N` and menu lists pending failed sessions when `.processed_log.json` has failures.

## [0.5.4] - 2026-06-30

### Added

- **`ideaforge --status --watch`** — Live-updating status view (default 2s interval; `--watch-interval` to customize).
- **Menubar Open Log** — Opens Terminal.app with `tail -f` on the daemon log (falls back to opening the file).

## [0.5.3] - 2026-06-30

### Added

- **`ideaforge --status`** — Pipeline state from `status.json`, daemon/menubar health, pending failure count, connected recorder.
- **`--status-json`** — Machine-readable status output for scripting.
- **`notify_on_failure`** — Opt-in macOS notification when a pipeline session fails (`[daemon]` config).

## [0.5.2] - 2026-06-30

### Added

- **Failed session persistence** — Failures stored in `~/IdeaForge/.processed_log.json` under `failures`; automatically retried on the next daemon or manual run.
- **`--retry-failed`** — Process only sessions that failed previously (`--source ~/IdeaForge`).
- **`--ingest-only`** — Copy, verify, purge (and optionally unmount) without transcribe/LLM; for testing device ingest.
- **`--no-unmount`** — Skip volume eject when used with `--ingest-only`.

### Changed

- Daemon retries pending failures even when no new files were ingested.
- Successful sessions clear their entry from the failure log.

## [0.5.1] - 2026-06-30

### Added

- **Daemon ingest-first** — Copy all device recordings to archive, verify hashes, delete sources, then unmount before transcribe/diarize/LLM runs on local files only.
- **`unmount_after_ingest`** — Config flag (default `true`) to eject the recorder volume after successful ingest.
- **Per-session failure isolation** — One bad session no longer blocks the rest of the queue.
- **Diarization progress** — `status.json` shows audio duration hint and segment labeling progress.
- **Menubar “Open Log”** — Menu item to open the daemon log.

### Changed

- Daemon default pipeline handler is `daemon_process_device` (ingest → process archive).
- Manual `ideaforge --auto-source` still copies/deletes inline per session (unchanged).

## [0.5.0] - 2026-06-30

### Added

- **Menu bar app** — `ideaforge-menubar` shows live pipeline progress (stage, percent, ETA) via `status.json`; install with `./scripts/install-menubar.sh`.
- **Parallel sessions** — `max_parallel_sessions` in config (default 1); pipelined processing so LLM notes can run while the next session transcribes/diarizes. GPU work serialized via `gpu_lock`.
- **`merge_min_chunk_seconds`** — Prevents short clips from merging into long recordings (default 600s).
- **`is_derived_audio()`** — Skips `*_merged*` artifacts during ingest and reprocess.
- **Daemon idle logging** — `No new recordings on {device} — skipping` when a volume has nothing new.
- **Scripts** — `install-menubar.sh`, `run-menubar.sh`, `stop-menubar.sh`, `uninstall-menubar.sh`.
- **Tests** — `test_status`, `test_menubar_lock`, `test_parallel`, expanded chunk/ingest/daemon coverage.

### Fixed

- **WAV merge** — `concat_wav_files` compares format params only (not `nframes`), so same-session chunks merge correctly.
- **Diarize warning** — Suppressed noisy torchcodec import warning when ffmpeg is available.
- **Menubar duplicates** — Singleton lock prevents multiple menu bar instances.

### Changed

- **Packaging** — `numpy` in core deps; `rumps` in `[all]` extra; version `0.5.0`.
- **Config example** — Documents `merge_min_chunk_seconds`, `max_parallel_sessions`, menubar.

## [0.4.0] and earlier

Prior releases were not changelogged in-repo. See git history for daemon, Grok/Claude/Ollama backends, faster-whisper + pyannote diarization, and USB ingest.

[1.0.1]: https://github.com/sm00thindian/IdeaForge/releases/tag/v1.0.1
[1.0.0]: https://github.com/sm00thindian/IdeaForge/releases/tag/v1.0.0
[0.9.0]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.9.0
[0.8.0]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.8.0
[0.7.1]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.7.1
[0.7.0]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.7.0
[0.6.2]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.6.2
[0.6.1]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.6.1
[0.6.0]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.6.0
[0.5.5]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.5
[0.5.4]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.4
[0.5.3]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.3
[0.5.2]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.2
[0.5.1]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.1
[0.5.0]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.0