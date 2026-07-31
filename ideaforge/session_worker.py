"""Per-session pipeline worker — copy, merge, transcribe, diarize, summarize."""

from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from ideaforge.audio_util import (
    compress_merged_wav_to_mp3,
    concat_wav_files,
    ensure_pipeline_audio,
    get_audio_duration_seconds,
    split_audio_fixed_window,
)
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
from ideaforge.session_layout import (
    ensure_session_dir,
    relocate_files_to_session_dir,
    resolve_date_folder,
    session_artifact_paths,
)
from ideaforge.transcribe import diarize_existing, transcribe_audio


def _purge_chunk_sources_after_merge(
    *,
    chunk_paths: Sequence[Path],
    pipeline_paths: Sequence[Path],
    merged_path: Path,
) -> int:
    """Delete per-chunk source WAVs (and normalize intermediates) after merge succeeds."""
    if not merged_path.is_file():
        return 0
    try:
        if merged_path.stat().st_size < 1_000:
            return 0
    except OSError:
        return 0

    merged_key = merged_path.resolve()
    to_remove: Set[Path] = set()
    for path in (*chunk_paths, *pipeline_paths):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved == merged_key:
            continue
        if path.suffix.lower() != ".wav":
            continue
        to_remove.add(path)

    removed = 0
    for path in sorted(to_remove, key=lambda item: str(item)):
        try:
            path.unlink()
            removed += 1
        except OSError:
            print(f"   ⚠️  Could not remove chunk after merge: {path.name}")
    return removed


def _purge_empty_merged_audio(
    *,
    process_path: Path,
    transcript_path: Path,
    enabled: bool = True,
) -> bool:
    """Delete merged WAV when transcription produced no words."""
    if not enabled:
        return False
    if not process_path.stem.endswith("_merged"):
        return False
    try:
        text = transcript_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if text:
        return False
    try:
        process_path.unlink()
        return True
    except OSError:
        print(f"   ⚠️  Could not remove empty merged audio: {process_path.name}")
        return False


def output_paths(folder: Path, stem: str) -> Dict[str, Path]:
    """Artifact map for a session working directory (nested or flat)."""
    return session_artifact_paths(folder, stem)


def summary_exists(paths: Dict[str, Path], output_format: str) -> bool:
    if output_format == "md":
        return paths["summary_md"].is_file()
    if output_format == "json":
        return paths["summary_json"].is_file()
    return paths["summary_md"].is_file() and paths["summary_json"].is_file()


def read_summary_brief(summary_json: Path, *, session_stem: str) -> RecordingResult:
    if not summary_json.exists():
        return RecordingResult(stem=session_stem)
    try:
        data = json.loads(summary_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return RecordingResult(stem=session_stem)
    from ideaforge.summary_names import creative_preview_lines, resolve_summary_md_path

    actions = data.get("action_items", [])
    metadata = data.get("metadata") or {}
    is_song = (
        data.get("intent") == "song_idea"
        or metadata.get("output_intent") == "song_idea"
    )
    if is_song:
        preview = creative_preview_lines(data)
    else:
        preview = [
            f"{a.get('who', 'TBD')}: {a.get('what', '')}"
            for a in actions[:2]
            if a.get("what")
        ]
    output_intent = data.get("intent") or metadata.get("output_intent")
    summary_md_path = resolve_summary_md_path(summary_json.parent, session_stem)
    return RecordingResult(
        stem=session_stem,
        title=data.get("title"),
        action_items=len(actions),
        action_preview=preview,
        output_intent=output_intent,
        summary_md=str(summary_md_path) if summary_md_path is not None else None,
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
    session_stem = group.session_stem
    if stages.copy:
        if group.recording_time is not None:
            date_folder = archive / group.recording_time.date_folder
        else:
            date_folder = archive_folder_for_file(group.files[0], archive)
        work_folder = ensure_session_dir(date_folder, session_stem)
    else:
        # In-place / daemon post-ingest / reprocess: nest under session package.
        # Flat date-folder files are relocated into the package below.
        audio_parent = group.files[0].parent
        date_folder = resolve_date_folder(audio_parent) or audio_parent
        if (
            audio_parent.name == session_stem
            and resolve_date_folder(audio_parent.parent) is not None
        ):
            work_folder = audio_parent
        else:
            work_folder = ensure_session_dir(date_folder, session_stem)
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
                session_stem=session_stem,
                paths=output_paths(work_folder, session_stem),
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
    date_folder = resolve_date_folder(work_folder) or work_folder

    if stages.copy:
        # Show date/session path when nested (e.g. 2026-07-20/R…/).
        rel = (
            f"{date_folder.name}/{work_folder.name}/"
            if work_folder != date_folder
            else f"{work_folder.name}/"
        )
        print(f"\n📼 {group.label} → {rel}")
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
        # Relocate flat date-folder (or mis-parented) files into the session package.
        relocated = relocate_files_to_session_dir(group.files, work_folder)
        copied_paths = list(relocated)
        for src, dest in zip(group.files, relocated):
            archive_copies[src] = dest
        if work_folder != date_folder and date_folder.is_dir():
            extras: List[Path] = []
            try:
                for child in date_folder.iterdir():
                    if not child.is_file():
                        continue
                    # Leave friendly day-root notes in place.
                    if child.suffix.lower() == ".md" and " - " in child.name:
                        continue
                    if child.stem == session_stem or child.stem.startswith(
                        f"{session_stem}_"
                    ):
                        extras.append(child)
            except OSError:
                extras = []
            if extras:
                relocate_files_to_session_dir(extras, work_folder)
        paths = output_paths(work_folder, session_stem)

    pipeline_paths = [
        ensure_pipeline_audio(
            path,
            work_folder,
            normalize_audio=cfg.normalize_audio,
        )
        for path in copied_paths
    ]

    merged_for_purge: Optional[Path] = None
    if len(pipeline_paths) > 1:
        if reporter is not None:
            reporter.set_step_active(
                StepId.MERGE,
                detail=f"Joining {len(pipeline_paths)} chunks",
            )
        merged_name = f"{session_stem}_merged.wav"
        process_path = concat_wav_files(pipeline_paths, work_folder / merged_name)
        print(f"   🔗 Merged {len(pipeline_paths)} chunks → {process_path.name}")
        merged_for_purge = process_path
        # Keep source chunks until ML succeeds so a Metal OOM / crash is recoverable.
        if reporter is not None:
            reporter.mark_step_done(StepId.MERGE)
    else:
        process_path = pipeline_paths[0]
        if reporter is not None and stages.transcribe:
            reporter.skip_step(StepId.MERGE)

    # Guard single huge files (or leftover overnight merges) against Metal OOM.
    process_path = _maybe_split_oversized_audio(
        process_path,
        work_folder=work_folder,
        session_stem=session_stem,
        max_session_seconds=cfg.max_session_seconds,
    )

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
            speaker_library_enabled=cfg.speaker_library_enabled,
            speaker_library_auto_apply=cfg.speaker_library_auto_apply,
            speaker_library_auto_learn=cfg.speaker_library_auto_learn,
            speaker_library_match_threshold=cfg.speaker_library_match_threshold,
            speaker_library_path=cfg.speaker_library_path,
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
            speaker_library_enabled=cfg.speaker_library_enabled,
            speaker_library_auto_apply=cfg.speaker_library_auto_apply,
            speaker_library_auto_learn=cfg.speaker_library_auto_learn,
            speaker_library_match_threshold=cfg.speaker_library_match_threshold,
            speaker_library_path=cfg.speaker_library_path,
        )
        if reporter is not None:
            reporter.mark_step_done(StepId.DIARIZE)
    elif stages.llm:
        if not transcript_path.exists():
            print(f"    ❌ Missing transcript: {transcript_path.name}")
            return 0, 0, RecordingResult(stem=session_stem)
        print("    📄 Using existing transcript")

    empty_recording = False
    gate_skip_reason: Optional[str] = None
    if (stages.transcribe or stages.diarize) and transcript_path:
        if _purge_empty_merged_audio(
            process_path=process_path,
            transcript_path=transcript_path,
            enabled=cfg.delete_empty_merged_audio,
        ):
            print(f"   🗑️  Removed empty recording audio: {process_path.name}")
            empty_recording = True
            gate_skip_reason = "empty transcript"

    if stages.llm and transcript_path and transcript_path.exists() and not empty_recording:
        from ideaforge.creative_intent import resolve_summarize_context
        from ideaforge.transcript_gate import assess_transcript_quality

        transcript_text = transcript_path.read_text(encoding="utf-8")
        gate = assess_transcript_quality(
            transcript_text,
            cfg.transcript_gate_settings(),
        )
        if gate.skip_llm:
            empty_recording = True
            gate_skip_reason = gate.reason or "low-quality transcript"
            print(f"   ⏭️  Skipping LLM — {gate_skip_reason}")
            if reporter is not None:
                reporter.skip_step(StepId.SUMMARIZE)
                reporter.touch(detail=f"Skipped LLM: {gate_skip_reason}")
        else:
            output_intent, summarize_label = resolve_summarize_context(
                transcript_text,
                cfg.mode,
                cfg.creative_settings(),
            )
            if reporter is not None:
                reporter.relabel_step(StepId.SUMMARIZE, summarize_label)
                reporter.set_output_intent(output_intent)
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
                recording_time=group.recording_time,
                creative_settings=cfg.creative_settings(),
                suno_style=cfg.creative_suno_style(),
                udio_style=cfg.creative_udio_style(),
                meeting_domain=cfg.meeting_domain,
                meeting_domain_terms=list(cfg.meeting_domain_terms),
            )
            if reporter is not None:
                reporter.mark_step_done(StepId.SUMMARIZE)

            from ideaforge.remote_sync import maybe_sync_after_notes

            maybe_sync_after_notes(
                work_folder=work_folder,
                archive_root=cfg.archive.expanduser().resolve(),
                device_root=archive,
                session_stem=session_stem,
                settings=cfg.sync_settings(),
                force=force,
            )

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

    # Only drop source chunks after a successful session (keeps overnight recoveries).
    if merged_for_purge is not None and not empty_recording:
        removed = _purge_chunk_sources_after_merge(
            chunk_paths=copied_paths,
            pipeline_paths=pipeline_paths,
            merged_path=merged_for_purge,
        )
        if removed:
            print(f"   🗑️  Removed {removed} chunk file(s) after successful session")
        # Archive the join as MP3 (small); ML already used the WAV merge.
        if cfg.merge_to_mp3 and merged_for_purge.is_file():
            try:
                wav_mb = merged_for_purge.stat().st_size / (1024 * 1024)
                mp3_path = compress_merged_wav_to_mp3(
                    merged_for_purge,
                    bitrate=cfg.merge_mp3_bitrate,
                    delete_wav=True,
                )
                mp3_mb = mp3_path.stat().st_size / (1024 * 1024)
                print(
                    f"   🎵 Compressed merge → {mp3_path.name} "
                    f"({wav_mb:.0f} MiB WAV → {mp3_mb:.1f} MiB MP3)"
                )
            except (RuntimeError, OSError, ValueError) as exc:
                print(f"   ⚠️  merge_to_mp3 skipped — kept WAV: {exc}")

    if empty_recording:
        brief = RecordingResult(
            stem=session_stem,
            empty=True,
            skip_reason=gate_skip_reason,
        )
    else:
        brief = read_summary_brief(paths["summary_json"], session_stem=session_stem)
    return 1, 0, brief


def _maybe_split_oversized_audio(
    process_path: Path,
    *,
    work_folder: Path,
    session_stem: str,
    max_session_seconds: float,
) -> Path:
    """
    If audio is longer than ``max_session_seconds``, process the first window only.

    Multi-chunk groups are capped at grouping time; this is a last-resort guard
    for a single huge file (e.g. leftover overnight merge). Metal cannot allocate
    buffers over ~4 GiB (~6–8h depending on sample format).
    """
    if max_session_seconds <= 0:
        return process_path
    try:
        duration = get_audio_duration_seconds(process_path)
    except (OSError, ValueError):
        return process_path
    if duration <= max_session_seconds:
        return process_path

    hours = duration / 3600.0
    cap_hours = max_session_seconds / 3600.0
    print(
        f"   ⚠️  Session audio is {hours:.1f}h (cap {cap_hours:.1f}h) — "
        f"Apple Metal max buffer is 4 GiB. Processing first {cap_hours:.1f}h only."
    )
    parts = split_audio_fixed_window(
        process_path,
        work_folder,
        window_seconds=max_session_seconds,
    )
    if len(parts) > 1:
        print(
            f"   ℹ️  Split into {len(parts)} window(s); later windows left as "
            f"{parts[1].name} … — re-run with --reprocess on those parts if needed"
        )
    if not parts:
        return process_path
    first = parts[0]
    print(f"   ✂️  Oversized audio → processing {first.name}")
    return first