# Changelog

All notable changes to IdeaForge are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

[0.5.5]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.5
[0.5.4]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.4
[0.5.3]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.3
[0.5.2]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.2
[0.5.1]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.1
[0.5.0]: https://github.com/sm00thindian/IdeaForge/releases/tag/v0.5.0