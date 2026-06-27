"""Pipeline execution for a single source folder."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Set

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore

from ideaforge.backends import resolve_whisper_backend
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
from ideaforge.pipeline import PipelineStages, should_skip_file
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
) -> None:
    from ideaforge import __version__

    print(f"🚀 IdeaForge v{__version__}")
    print(f"   Source:  {source}")
    print(f"   Archive: {archive}")
    print(f"   Pipeline: {stages.label}")
    print(f"   Mode: {cfg.mode} | LLM: {cfg.llm_backend} | Output: {cfg.output_format}")
    if stages.transcribe:
        whisper_backend = resolve_whisper_backend(cfg.whisper_backend)
        print(f"   Whisper: {whisper_backend} ({cfg.whisper_model})")
    if stages.diarize:
        hint = f"min={cfg.min_speakers}" if cfg.min_speakers else "min=auto"
        print(f"   Diarize: pyannote ({hint})")
    if cfg.speaker_map:
        print(
            f"   Speakers: {len(cfg.speaker_map)} manual override(s) "
            "(Grok infers names by default)"
        )
    print(f"   Found {audio_count} audio file(s)")


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
) -> int:
    """Run the configured pipeline on all audio files under source. Returns files touched."""
    extensions: Set[str] = set(cfg.audio_extensions)
    audio_files = get_audio_files(source, extensions, cfg.min_file_size_bytes)

    if show_header:
        print_run_header(
            source=source,
            archive=archive,
            stages=stages,
            cfg=cfg,
            audio_count=len(audio_files),
        )

    if not audio_files:
        print("    ℹ️  No audio files to process")
        return 0

    processed_log = load_processed_log(archive)
    newly_processed = 0
    iterator = tqdm(audio_files, desc="Processing") if show_progress and tqdm else audio_files

    for audio_file in iterator:
        try:
            source_hash = compute_file_hash(audio_file)
        except OSError:
            print(f"\n⚠️  Cannot read {audio_file.name} — skipping")
            continue

        date_folder = archive_folder_for_file(audio_file, archive)
        work_folder = date_folder if stages.copy else audio_file.parent
        paths = _output_paths(work_folder, audio_file.stem)
        already_processed = source_hash in processed_log.get("hashes", [])

        if should_skip_file(
            stages=stages,
            force=force,
            already_processed=already_processed,
            transcript_exists=paths["transcript"].exists(),
            summary_exists=_summary_exists(paths, cfg.output_format),
            diarized_exists=paths["diarized"].exists(),
        ):
            print(f"\n⏭️  Skipping {audio_file.name} (outputs exist — use --force to redo)")
            if stages.copy and delete_from_device:
                archive_copy = find_archive_copy(audio_file, archive, processed_log)
                if archive_copy:
                    _try_remove_from_device(
                        audio_file,
                        archive_copy,
                        enabled=True,
                    )
            continue

        process_path = audio_file
        archive_copy: Optional[Path] = None
        if stages.copy:
            print(f"\n📼 {audio_file.name} → {work_folder.name}/")
            process_path = copy_file_safely(audio_file, work_folder)
            archive_copy = process_path
            paths = _output_paths(work_folder, audio_file.stem)
            print("   📥 Copied to archive")
        else:
            print(f"\n📼 {audio_file.name} (in-place)")

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
                diarize=stages.diarize,
                hf_token=cfg.hf_token,
                min_speakers=cfg.min_speakers,
                max_speakers=cfg.max_speakers,
                speaker_map=cfg.speaker_map,
                force=force,
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
            )
        elif stages.llm:
            if not transcript_path.exists():
                print(f"    ❌ Missing transcript: {transcript_path.name}")
                continue
            print("    📄 Using existing transcript")

        if stages.llm and transcript_path and transcript_path.exists():
            process_transcript(
                transcript_path,
                work_folder,
                mode=cfg.mode,  # type: ignore[arg-type]
                backend=cfg.llm_backend,
                ollama_model=cfg.ollama_model,
                grok_model=cfg.grok_model,
                claude_model=cfg.claude_model,
                output_format=cfg.output_format,
                force=force,
                archive=archive,
                export_settings=export_settings,
            )

        if stages.copy or stages.transcribe:
            record_processed(
                processed_log,
                audio_file,
                work_folder,
                archive_file=process_path if stages.copy else None,
                file_hash=source_hash,
            )

        if archive_copy is not None:
            _try_remove_from_device(
                audio_file,
                archive_copy,
                enabled=delete_from_device,
            )

        newly_processed += 1

    save_processed_log(archive, processed_log)
    print(f"\n✅ IdeaForge complete — {newly_processed} file(s) processed")
    return newly_processed