"""Pipeline execution for a single source folder."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore

from ideaforge.audio_util import concat_wav_files
from ideaforge.backends import resolve_whisper_backend
from ideaforge.chunks import RecordingGroup, group_recordings
from ideaforge.config import IdeaForgeConfig
from ideaforge.device import is_path_on_recorder
from ideaforge.ingest import (
    archive_folder_for_file,
    archive_paths_for_failed_sessions,
    clear_session_failure,
    compute_file_hash,
    copy_file_safely,
    expand_scope_files,
    failed_session_stems,
    find_archive_copy,
    get_audio_files,
    is_derived_audio,
    load_processed_log,
    record_processed,
    record_session_failure,
    remove_device_file_after_copy,
    save_processed_log,
)
from ideaforge.llm import process_transcript
from ideaforge.notify import ProcessResult, RecordingResult, notify_session_failure
from ideaforge.pipeline import PipelineStages, should_skip_group
from ideaforge.status import StatusReporter, active_reporter, build_step_plan
from ideaforge.transcribe import diarize_existing, transcribe_audio


def _output_paths(folder: Path, stem: str) -> dict:
    return {
        "transcript": folder / f"{stem}.txt",
        "summary_md": folder / f"{stem}_summary.md",
        "summary_json": folder / f"{stem}_summary.json",
        "diarized": folder / f"{stem}_diarized.json",
        "segments": folder / f"{stem}_segments.json",
    }


def _summary_exists(paths: dict, output_format: str) -> bool:
    if output_format == "md":
        return paths["summary_md"].exists()
    if output_format == "json":
        return paths["summary_json"].exists()
    return paths["summary_md"].exists() and paths["summary_json"].exists()


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


def _try_remove_from_device(
    source_file: Path,
    archive_copy: Path,
    *,
    enabled: bool,
) -> None:
    if not enabled or not is_path_on_recorder(source_file):
        return
    if remove_device_file_after_copy(source_file, archive_copy):
        print(f"   🗑️  Removed from device: {source_file.name}")
    else:
        print(f"   ⚠️  Kept on device — archive copy not verified: {source_file.name}")


def _read_summary_brief(summary_json: Path, *, session_stem: str) -> RecordingResult:
    if not summary_json.exists():
        return RecordingResult(stem=session_stem)
    try:
        data = json.loads(summary_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return RecordingResult(stem=session_stem)
    actions = data.get("action_items", [])
    preview = [
        f"{a.get('who', 'TBD')}: {a.get('what', '')}"
        for a in actions[:2]
        if a.get("what")
    ]
    return RecordingResult(
        stem=session_stem,
        title=data.get("title"),
        action_items=len(actions),
        action_preview=preview,
    )


def _hash_group_files(group: RecordingGroup) -> Dict[Path, str]:
    hashes: Dict[Path, str] = {}
    for audio_file in group.files:
        hashes[audio_file] = compute_file_hash(audio_file)
    return hashes


def _process_group(
    group: RecordingGroup,
    archive: Path,
    cfg: IdeaForgeConfig,
    stages: PipelineStages,
    processed_log: dict,
    *,
    force: bool,
    delete_from_device: bool,
    export_settings=None,
    session_index: int = 1,
    sessions_total: int = 1,
    log_lock: Optional[threading.Lock] = None,
) -> tuple[int, int, RecordingResult]:
    """Process one recording session. Returns (processed, skipped, brief)."""
    work_folder = (
        archive_folder_for_file(group.files[0], archive)
        if stages.copy
        else group.files[0].parent
    )
    reporter = active_reporter()
    session_tracker = (
        reporter.track_session() if reporter is not None else nullcontext()
    )
    file_hashes = _hash_group_files(group)
    with session_tracker:
        try:
            return _process_group_body(
                group,
                archive,
                cfg,
                stages,
                processed_log,
                force=force,
                delete_from_device=delete_from_device,
                export_settings=export_settings,
                session_index=session_index,
                sessions_total=sessions_total,
                log_lock=log_lock,
                reporter=reporter,
                file_hashes=file_hashes,
                work_folder=work_folder,
                session_stem=group.session_stem,
                paths=_output_paths(work_folder, group.session_stem),
            )
        except Exception as exc:
            _record_failure_locked(
                processed_log,
                log_lock=log_lock,
                group=group,
                archive=archive,
                work_folder=work_folder,
                file_hashes=file_hashes,
                exc=exc,
                stages=stages,
            )
            raise


def _record_failure_locked(
    processed_log: dict,
    *,
    log_lock: Optional[threading.Lock],
    group: RecordingGroup,
    archive: Path,
    work_folder: Path,
    file_hashes: Dict[Path, str],
    exc: Exception,
    stages: PipelineStages,
) -> None:
    archive_files = list(group.files)
    if stages.copy:
        archive_files = [
            find_archive_copy(audio_file, archive, processed_log) or audio_file
            for audio_file in group.files
        ]
    payload = dict(
        session_stem=group.session_stem,
        archive_folder=work_folder,
        archive_files=archive_files,
        chunk_hashes=list(file_hashes.values()),
        error=str(exc),
        pipeline=stages.label,
    )
    if log_lock is None:
        record_session_failure(processed_log, **payload)
        return
    with log_lock:
        record_session_failure(processed_log, **payload)


def _record_processed_locked(
    processed_log: dict,
    *,
    log_lock: Optional[threading.Lock],
    source_file: Path,
    archive_path: Path,
    archive_file: Optional[Path] = None,
    file_hash: Optional[str] = None,
) -> None:
    if log_lock is None:
        record_processed(
            processed_log,
            source_file,
            archive_path,
            archive_file=archive_file,
            file_hash=file_hash,
        )
        return
    with log_lock:
        record_processed(
            processed_log,
            source_file,
            archive_path,
            archive_file=archive_file,
            file_hash=file_hash,
        )


def _process_group_body(
    group: RecordingGroup,
    archive: Path,
    cfg: IdeaForgeConfig,
    stages: PipelineStages,
    processed_log: dict,
    *,
    force: bool,
    delete_from_device: bool,
    export_settings,
    session_index: int,
    sessions_total: int,
    log_lock: Optional[threading.Lock],
    reporter: Optional[StatusReporter],
    file_hashes: Dict[Path, str],
    work_folder: Path,
    session_stem: str,
    paths: dict,
) -> tuple[int, int, RecordingResult]:
    if reporter is not None:
        reporter.begin_session(
            session_index,
            label=group.label,
            recording_stem=session_stem,
            step_plan=build_step_plan(stages),
        )

    processed_hashes = processed_log.get("hashes", [])
    is_failed_retry = session_stem in processed_log.get("failures", {})
    if is_failed_retry:
        prior = processed_log["failures"][session_stem]
        print(
            f"\n↻ Retrying failed session {group.label} "
            f"({prior.get('error', 'unknown error')})"
        )

    if not is_failed_retry and should_skip_group(
        stages=stages,
        force=force,
        chunk_hashes=list(file_hashes.values()),
        processed_hashes=processed_hashes,
        transcript_exists=paths["transcript"].exists(),
        summary_exists=_summary_exists(paths, cfg.output_format),
        diarized_exists=paths["diarized"].exists(),
    ):
        print(f"\n⏭️  Skipping {group.label} (outputs exist — use --force to redo)")
        if stages.copy and delete_from_device:
            for audio_file in group.files:
                archive_copy = find_archive_copy(audio_file, archive, processed_log)
                if archive_copy:
                    _try_remove_from_device(audio_file, archive_copy, enabled=True)
        brief = _read_summary_brief(paths["summary_json"], session_stem=session_stem)
        brief.skipped = True
        return 0, 1, brief

    copied_paths: List[Path] = []
    archive_copies: Dict[Path, Path] = {}

    if stages.copy:
        print(f"\n📼 {group.label} → {work_folder.name}/")
        if reporter is not None:
            reporter.set_step_active("copy", detail=f"0/{len(group.files)} files")
        for index, audio_file in enumerate(group.files, start=1):
            copied = copy_file_safely(audio_file, work_folder)
            copied_paths.append(copied)
            archive_copies[audio_file] = copied
            if reporter is not None:
                reporter.touch(
                    stage="Copying",
                    progress=index / len(group.files),
                    detail=f"{index}/{len(group.files)} files copied",
                )
        print("   📥 Copied to archive")
        if reporter is not None:
            reporter.mark_step_done("copy")
    else:
        print(f"\n📼 {group.label} (in-place)")
        copied_paths = list(group.files)
        for audio_file in group.files:
            archive_copies[audio_file] = audio_file

    if len(copied_paths) > 1:
        if reporter is not None:
            reporter.set_step_active(
                "merge",
                detail=f"Joining {len(copied_paths)} chunks",
            )
        merged_name = f"{session_stem}_merged{copied_paths[0].suffix}"
        process_path = concat_wav_files(copied_paths, work_folder / merged_name)
        print(f"   🔗 Merged {len(copied_paths)} chunks → {process_path.name}")
        if reporter is not None:
            reporter.mark_step_done("merge")
    else:
        process_path = copied_paths[0]
        if reporter is not None and stages.transcribe:
            reporter.skip_step("merge")

    transcript_path = paths["transcript"]

    if stages.transcribe:
        if reporter is not None:
            reporter.set_step_active("transcribe", detail=process_path.name)
        transcript_path = transcribe_audio(
            process_path,
            work_folder,
            whisper_backend=cfg.whisper_backend,
            whisper_model=cfg.whisper_model,
            whisper_device=cfg.whisper_device,
            whisper_compute_type=cfg.whisper_compute_type,
            beam_size=cfg.whisper_beam_size,
            language=cfg.whisper_language,
            diarize=stages.diarize,
            hf_token=cfg.hf_token,
            min_speakers=cfg.min_speakers,
            max_speakers=cfg.max_speakers,
            speaker_map=cfg.speaker_map,
            force=force,
            output_stem=session_stem,
        )
        if reporter is not None:
            reporter.mark_step_done("transcribe")
    elif stages.diarize:
        if reporter is not None:
            reporter.set_step_active("diarize", detail=process_path.name)
        transcript_path = diarize_existing(
            process_path,
            work_folder,
            hf_token=cfg.hf_token,
            min_speakers=cfg.min_speakers,
            max_speakers=cfg.max_speakers,
            speaker_map=cfg.speaker_map,
            force=force,
            output_stem=session_stem,
        )
        if reporter is not None:
            reporter.mark_step_done("diarize")
    elif stages.llm:
        if not transcript_path.exists():
            print(f"    ❌ Missing transcript: {transcript_path.name}")
            brief = RecordingResult(stem=session_stem)
            return 0, 0, brief
        print("    📄 Using existing transcript")

    if stages.llm and transcript_path and transcript_path.exists():
        if reporter is not None:
            reporter.set_step_active("summarize", detail=transcript_path.stem)
        process_transcript(
            transcript_path,
            work_folder,
            mode=cfg.mode,  # type: ignore[arg-type]
            backend=cfg.resolve_llm_backend(),
            ollama_model=cfg.ollama_model,
            grok_model=cfg.grok_model,
            claude_model=cfg.claude_model,
            output_format=cfg.output_format,
            force=force,
            archive=archive,
            export_settings=export_settings,
        )
        if reporter is not None:
            reporter.mark_step_done("summarize")

    if stages.copy or stages.transcribe:
        for audio_file, file_hash in file_hashes.items():
            _record_processed_locked(
                processed_log,
                log_lock=log_lock,
                source_file=audio_file,
                archive_path=work_folder,
                archive_file=archive_copies.get(audio_file),
                file_hash=file_hash,
            )

    if log_lock is None:
        clear_session_failure(processed_log, session_stem)
    else:
        with log_lock:
            clear_session_failure(processed_log, session_stem)

    if delete_from_device:
        for audio_file, archive_copy in archive_copies.items():
            _try_remove_from_device(audio_file, archive_copy, enabled=True)

    brief = _read_summary_brief(paths["summary_json"], session_stem=session_stem)
    return 1, 0, brief


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
    processed_log = load_processed_log(archive)

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
    log_lock = threading.Lock() if workers > 1 else None

    def _run_session(
        session_index: int,
        group: RecordingGroup,
    ) -> tuple[int, int, RecordingResult]:
        return _process_group(
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
        if workers <= 1:
            iterator = (
                tqdm(groups, desc="Processing") if show_progress and tqdm else groups
            )
            for session_index, group in enumerate(iterator, start=1):
                try:
                    processed, skipped, brief = _run_session(session_index, group)
                except Exception as exc:
                    _handle_session_failure(
                        group,
                        exc,
                        reporter=reporter,
                        notify=cfg.notify_on_failure,
                    )
                    brief = RecordingResult(stem=group.session_stem, failed=True)
                    result.recordings.append(brief)
                    continue
                result.files_processed += processed
                result.files_skipped += skipped
                result.recordings.append(brief)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_run_session, index, group): group
                    for index, group in enumerate(groups, start=1)
                }
                for future in as_completed(futures):
                    group = futures[future]
                    try:
                        processed, skipped, brief = future.result()
                    except Exception as exc:
                        _handle_session_failure(
                            group,
                            exc,
                            reporter=reporter,
                            notify=cfg.notify_on_failure,
                        )
                        brief = RecordingResult(stem=group.session_stem, failed=True)
                        result.recordings.append(brief)
                        continue
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