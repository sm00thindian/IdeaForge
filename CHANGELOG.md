# Changelog

All notable changes to IdeaForge are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

[0.5.0]: https://github.com/kilynn/IdeaForge/releases/tag/v0.5.0