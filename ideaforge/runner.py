"""Pipeline execution for a single source folder."""

from __future__ import annotations

import json
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
    compute_file_hash,
    copy_file_safely,
    find_archive_copy,
    get_audio_files,
    load_processed_log,
    record_processed,
    remove_device_file_after_copy,
    save_processed_log,
)
from ideaforge.llm import process_transcript
from ideaforge.notify import ProcessResult, RecordingResult
from ideaforge.pipeline import PipelineStages, should_skip_group
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
            f"(merging chunks ≤ {cfg.chunk_gap_seconds:.0f}s apart)"
        )
    else:
        print(f"   Found {audio_count} audio file(s)")
    if cfg.speaker_map:
        print(
            f"   Speakers: {len(cfg.speaker_map)} manual override(s) "
            "(Grok infers names by default)"
        )


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
) -> tuple[int, int, RecordingResult]:
    """Process one recording session. Returns (processed, skipped, brief)."""
    file_hashes = _hash_group_files(group)
    date_folder = archive_folder_for_file(group.files[0], archive)
    work_folder = date_folder if stages.copy else group.files[0].parent
    session_stem = group.session_stem
    paths = _output_paths(work_folder, session_stem)
    processed_hashes = processed_log.get("hashes", [])

    if should_skip_group(
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
        for audio_file in group.files:
            copied = copy_file_safely(audio_file, work_folder)
            copied_paths.append(copied)
            archive_copies[audio_file] = copied
        print("   📥 Copied to archive")
    else:
        print(f"\n📼 {group.label} (in-place)")
        copied_paths = list(group.files)
        for audio_file in group.files:
            archive_copies[audio_file] = audio_file

    if len(copied_paths) > 1:
        merged_name = f"{session_stem}_merged{copied_paths[0].suffix}"
        process_path = concat_wav_files(copied_paths, work_folder / merged_name)
        print(f"   🔗 Merged {len(copied_paths)} chunks → {process_path.name}")
    else:
        process_path = copied_paths[0]

    transcript_path = paths["transcript"]

    if stages.transcribe:
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
    elif stages.diarize:
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
    elif stages.llm:
        if not transcript_path.exists():
            print(f"    ❌ Missing transcript: {transcript_path.name}")
            brief = RecordingResult(stem=session_stem)
            return 0, 0, brief
        print("    📄 Using existing transcript")

    if stages.llm and transcript_path and transcript_path.exists():
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

    if stages.copy or stages.transcribe:
        for audio_file, file_hash in file_hashes.items():
            record_processed(
                processed_log,
                audio_file,
                work_folder,
                archive_file=archive_copies.get(audio_file),
                file_hash=file_hash,
            )

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
) -> ProcessResult:
    """Run the configured pipeline on all audio files under source."""
    extensions: Set[str] = set(cfg.audio_extensions)
    audio_files = get_audio_files(source, extensions, cfg.min_file_size_bytes)
    groups = group_recordings(
        audio_files,
        enabled=cfg.merge_chunks,
        chunk_gap_seconds=cfg.chunk_gap_seconds,
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

    processed_log = load_processed_log(archive)
    result = ProcessResult()
    iterator = tqdm(groups, desc="Processing") if show_progress and tqdm else groups

    for group in iterator:
        try:
            processed, skipped, brief = _process_group(
                group,
                archive,
                cfg,
                stages,
                processed_log,
                force=force,
                delete_from_device=delete_from_device,
                export_settings=export_settings,
            )
        except OSError as exc:
            print(f"\n⚠️  Cannot process {group.label} — {exc}")
            continue
        except ValueError as exc:
            print(f"\n⚠️  Cannot merge {group.label} — {exc}")
            continue

        result.files_processed += processed
        result.files_skipped += skipped
        result.recordings.append(brief)

    save_processed_log(archive, processed_log)
    print(f"\n✅ IdeaForge complete — {result.files_processed} session(s) processed")
    return result