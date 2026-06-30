"""Pipeline orchestration for a source folder."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set

from ideaforge.backends import resolve_whisper_backend
from ideaforge.chunks import RecordingGroup, group_recordings
from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import (
    archive_paths_for_failed_sessions,
    expand_scope_files,
    failed_session_stems,
    get_audio_files,
    is_derived_audio,
    load_processed_log,
    save_processed_log,
)
from ideaforge.notify import ProcessResult, RecordingResult, notify_session_failure
from ideaforge.pipeline import PipelineStages
from ideaforge.session_pool import run_session_groups, session_log_lock
from ideaforge.session_worker import process_group
from ideaforge.state_db import ProcessedLog
from ideaforge.status import StatusReporter


def print_run_header(
    *,
    source: Path,
    archive: Path,
    stages: PipelineStages,
    cfg: IdeaForgeConfig,
    audio_count: int,
    session_count: int,
) -> None:
    from ideaforge import __version__

    print(f"🚀 IdeaForge v{__version__}")
    print(f"   Source:  {source}")
    print(f"   Archive: {archive}")
    print(f"   Pipeline: {stages.label}")
    print(
        f"   Mode: {cfg.mode} | LLM: {cfg.resolve_llm_backend()} | Output: {cfg.output_format}"
    )
    if stages.transcribe:
        whisper_backend = resolve_whisper_backend(cfg.whisper_backend)
        print(f"   Whisper: {whisper_backend} ({cfg.whisper_model})")
    if stages.diarize:
        hint = f"min={cfg.min_speakers}" if cfg.min_speakers else "min=auto"
        print(f"   Diarize: pyannote ({hint})")
    if cfg.merge_chunks and session_count < audio_count:
        print(
            f"   Found {audio_count} audio file(s) in {session_count} session(s) "
            f"(merging auto-split chunks ≤ {cfg.chunk_gap_seconds:.0f}s apart, "
            f"≥ {cfg.merge_min_chunk_seconds:.0f}s long)"
        )
    else:
        print(f"   Found {audio_count} audio file(s)")
    if cfg.max_parallel_sessions > 1 and session_count > 1:
        print(
            f"   Parallel: up to {cfg.max_parallel_sessions} session(s) "
            "(GPU stages serialized, LLM may overlap)"
        )
    if cfg.speaker_map:
        print(
            f"   Speakers: {len(cfg.speaker_map)} manual override(s) "
            "(Grok infers names by default)"
        )


def _handle_session_failure(
    group: RecordingGroup,
    exc: Exception,
    *,
    reporter: Optional[StatusReporter],
    notify: bool,
) -> None:
    print(f"\n⚠️  Session failed {group.label} — {exc}")
    if reporter is not None:
        reporter.set_error(str(exc))
    if notify:
        notify_session_failure(group.session_stem, str(exc))


def process_source(
    source: Path,
    archive: Path,
    cfg: IdeaForgeConfig,
    stages: PipelineStages,
    *,
    force: bool = False,
    delete_from_device: bool = False,
    export_settings=None,
    show_header: bool = True,
    show_progress: bool = True,
    scope_files: Optional[List[Path]] = None,
    retry_failed_only: bool = False,
    include_failed_retries: bool = True,
) -> ProcessResult:
    """Run the configured pipeline on all audio files under source."""
    extensions: Set[str] = set(cfg.audio_extensions)
    processed_log: ProcessedLog = load_processed_log(archive)

    if retry_failed_only:
        scoped = archive_paths_for_failed_sessions(
            processed_log,
            min_size_bytes=cfg.min_file_size_bytes,
        )
    else:
        scoped = expand_scope_files(
            scope_files,
            processed_log,
            min_size_bytes=cfg.min_file_size_bytes,
            include_failures=include_failed_retries,
        )

    if scoped is not None:
        audio_files = sorted(
            {
                path
                for path in scoped
                if path.is_file()
                and path.stat().st_size >= cfg.min_file_size_bytes
                and not is_derived_audio(path)
            },
            key=lambda p: p.stat().st_mtime,
        )
    else:
        audio_files = get_audio_files(source, extensions, cfg.min_file_size_bytes)
    groups = group_recordings(
        audio_files,
        enabled=cfg.merge_chunks,
        chunk_gap_seconds=cfg.chunk_gap_seconds,
        merge_min_chunk_seconds=cfg.merge_min_chunk_seconds,
    )

    if show_header:
        print_run_header(
            source=source,
            archive=archive,
            stages=stages,
            cfg=cfg,
            audio_count=len(audio_files),
            session_count=len(groups),
        )

    if not groups:
        print("    ℹ️  No audio files to process")
        return ProcessResult()

    device_label = source.name
    reporter = StatusReporter()
    result = ProcessResult()
    failed_pending = failed_session_stems(processed_log)
    if failed_pending:
        print(f"   ↻ Retrying {len(failed_pending)} failed session(s) from prior run")
    workers = min(cfg.max_parallel_sessions, len(groups))
    log_lock = session_log_lock(workers)

    def _run_session(
        session_index: int,
        group: RecordingGroup,
    ) -> tuple[int, int, RecordingResult]:
        return process_group(
            group,
            archive,
            cfg,
            stages,
            processed_log,
            force=force,
            delete_from_device=delete_from_device,
            export_settings=export_settings,
            session_index=session_index,
            sessions_total=len(groups),
            log_lock=log_lock,
        )

    with reporter.activate():
        reporter.begin_run(
            device=device_label,
            sessions_total=len(groups),
            pipeline=stages.label,
        )
        recordings = run_session_groups(
            groups,
            run_one=_run_session,
            max_workers=workers,
            reporter=reporter,
            on_failure=lambda group, exc: _handle_session_failure(
                group,
                exc,
                reporter=reporter,
                notify=cfg.notify_on_failure,
            ),
            show_progress=show_progress,
        )
        for processed, skipped, brief in recordings:
            result.files_processed += processed
            result.files_skipped += skipped
            result.recordings.append(brief)

        save_processed_log(archive, processed_log)
        reporter.complete_run(
            processed=result.files_processed,
            skipped=result.files_skipped,
        )

    print(f"\n✅ IdeaForge complete — {result.files_processed} session(s) processed")
    return result