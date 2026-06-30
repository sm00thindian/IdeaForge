"""Per-session pipeline worker — copy, merge, transcribe, diarize, summarize."""

from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Dict, List, Optional

from ideaforge.audio_util import concat_wav_files
from ideaforge.chunks import RecordingGroup
from ideaforge.config import IdeaForgeConfig
from ideaforge.device import is_path_on_recorder
from ideaforge.ingest import (
    archive_folder_for_file,
    compute_file_hash,
    copy_file_safely,
    find_archive_copy,
    record_processed,
    remove_device_file_after_copy,
)
from ideaforge.state_db import clear_session_failure, record_session_failure
from ideaforge.llm import process_transcript
from ideaforge.notify import RecordingResult
from ideaforge.pipeline import PipelineStages, should_skip_group
from ideaforge.state_db import ProcessedLogLike
from ideaforge.status import (
    Stage,
    StatusReporter,
    StepId,
    active_reporter,
    build_step_plan,
)
from ideaforge.transcribe import diarize_existing, transcribe_audio


def output_paths(folder: Path, stem: str) -> Dict[str, Path]:
    return {
        "transcript": folder / f"{stem}.txt",
        "summary_md": folder / f"{stem}_summary.md",
        "summary_json": folder / f"{stem}_summary.json",
        "diarized": folder / f"{stem}_diarized.json",
        "segments": folder / f"{stem}_segments.json",
    }


def summary_exists(paths: Dict[str, Path], output_format: str) -> bool:
    if output_format == "md":
        return paths["summary_md"].exists()
    if output_format == "json":
        return paths["summary_json"].exists()
    return paths["summary_md"].exists() and paths["summary_json"].exists()


def read_summary_brief(summary_json: Path, *, session_stem: str) -> RecordingResult:
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
    return {audio_file: compute_file_hash(audio_file) for audio_file in group.files}


def try_remove_from_device(
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


def record_failure_locked(
    processed_log: ProcessedLogLike,
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


def record_processed_locked(
    processed_log: ProcessedLogLike,
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


def process_group(
    group: RecordingGroup,
    archive: Path,
    cfg: IdeaForgeConfig,
    stages: PipelineStages,
    processed_log: ProcessedLogLike,
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
                paths=output_paths(work_folder, group.session_stem),
            )
        except Exception as exc:
            record_failure_locked(
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


def _process_group_body(
    group: RecordingGroup,
    archive: Path,
    cfg: IdeaForgeConfig,
    stages: PipelineStages,
    processed_log: ProcessedLogLike,
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
    paths: Dict[str, Path],
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
        summary_exists=summary_exists(paths, cfg.output_format),
        diarized_exists=paths["diarized"].exists(),
    ):
        print(f"\n⏭️  Skipping {group.label} (outputs exist — use --force to redo)")
        if stages.copy and delete_from_device:
            for audio_file in group.files:
                archive_copy = find_archive_copy(audio_file, archive, processed_log)
                if archive_copy:
                    try_remove_from_device(audio_file, archive_copy, enabled=True)
        brief = read_summary_brief(paths["summary_json"], session_stem=session_stem)
        brief.skipped = True
        return 0, 1, brief

    copied_paths: List[Path] = []
    archive_copies: Dict[Path, Path] = {}

    if stages.copy:
        print(f"\n📼 {group.label} → {work_folder.name}/")
        if reporter is not None:
            reporter.set_step_active(StepId.COPY, detail=f"0/{len(group.files)} files")
        for index, audio_file in enumerate(group.files, start=1):
            copied = copy_file_safely(audio_file, work_folder)
            copied_paths.append(copied)
            archive_copies[audio_file] = copied
            if reporter is not None:
                reporter.touch(
                    stage=Stage.COPYING,
                    progress=index / len(group.files),
                    detail=f"{index}/{len(group.files)} files copied",
                )
        print("   📥 Copied to archive")
        if reporter is not None:
            reporter.mark_step_done(StepId.COPY)
    else:
        print(f"\n📼 {group.label} (in-place)")
        copied_paths = list(group.files)
        for audio_file in group.files:
            archive_copies[audio_file] = audio_file

    if len(copied_paths) > 1:
        if reporter is not None:
            reporter.set_step_active(
                StepId.MERGE,
                detail=f"Joining {len(copied_paths)} chunks",
            )
        merged_name = f"{session_stem}_merged{copied_paths[0].suffix}"
        process_path = concat_wav_files(copied_paths, work_folder / merged_name)
        print(f"   🔗 Merged {len(copied_paths)} chunks → {process_path.name}")
        if reporter is not None:
            reporter.mark_step_done(StepId.MERGE)
    else:
        process_path = copied_paths[0]
        if reporter is not None and stages.transcribe:
            reporter.skip_step(StepId.MERGE)

    transcript_path = paths["transcript"]

    if stages.transcribe:
        if reporter is not None:
            reporter.set_step_active(StepId.TRANSCRIBE, detail=process_path.name)
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
            reporter.mark_step_done(StepId.TRANSCRIBE)
    elif stages.diarize:
        if reporter is not None:
            reporter.set_step_active(StepId.DIARIZE, detail=process_path.name)
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
            reporter.mark_step_done(StepId.DIARIZE)
    elif stages.llm:
        if not transcript_path.exists():
            print(f"    ❌ Missing transcript: {transcript_path.name}")
            return 0, 0, RecordingResult(stem=session_stem)
        print("    📄 Using existing transcript")

    if stages.llm and transcript_path and transcript_path.exists():
        if reporter is not None:
            reporter.set_step_active(StepId.SUMMARIZE, detail=transcript_path.stem)
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
            reporter.mark_step_done(StepId.SUMMARIZE)

    if stages.copy or stages.transcribe:
        for audio_file, file_hash in file_hashes.items():
            record_processed_locked(
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
            try_remove_from_device(audio_file, archive_copy, enabled=True)

    brief = read_summary_brief(paths["summary_json"], session_stem=session_stem)
    return 1, 0, brief