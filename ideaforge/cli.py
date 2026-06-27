"""IdeaForge CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Set

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore

from ideaforge import __version__
from ideaforge.config import IdeaForgeConfig, load_dotenv
from ideaforge.device import auto_detect_source, describe_device, find_recorder_mounts
from ideaforge.ingest import (
    archive_folder_for_file,
    copy_file_safely,
    compute_file_hash,
    get_audio_files,
    load_processed_log,
    record_processed,
    save_processed_log,
    should_skip_by_hash,
)
from ideaforge.llm import process_transcript
from ideaforge.backends import resolve_whisper_backend
from ideaforge.transcribe import transcribe_audio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ideaforge",
        description="IdeaForge — Local-first pipeline for USB voice recorders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  ideaforge --auto-source                          # detect recorder, full pipeline
  ideaforge --source "/Volumes/NO NAME" --list-only
  ideaforge --source /Volumes/Z29 --mode meeting --diarize
  ideaforge --auto-source --mode meeting   # uses Grok automatically if XAI_API_KEY is set
  ideaforge --source ~/recordings --no-copy --no-llm  # transcribe only
""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source", type=Path, help="Mounted recorder or folder path")
    source.add_argument(
        "--auto-source",
        action="store_true",
        help="Auto-detect USB recorder under /Volumes",
    )

    parser.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="Archive root (default: ~/IdeaForge)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config.toml (default: ~/.config/ideaforge/config.toml)",
    )

    # Pipeline stages
    parser.add_argument("--no-copy", action="store_true", help="Skip copying to archive")
    parser.add_argument("--no-transcribe", action="store_true", help="Skip transcription")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM summarization")
    parser.add_argument("--force", action="store_true", help="Reprocess even if outputs exist")
    parser.add_argument("--list-only", action="store_true", help="List audio files and exit")
    parser.add_argument("--detect", action="store_true", help="Show detected recorders and exit")

    # Transcription
    parser.add_argument(
        "--whisper-model",
        default=None,
        choices=["tiny", "base", "small", "medium", "large-v3"],
    )
    parser.add_argument(
        "--whisper-backend",
        default=None,
        choices=["auto", "mlx", "faster"],
        help="Transcription backend (default: auto — mlx on Apple Silicon)",
    )
    parser.add_argument(
        "--diarize",
        action="store_true",
        help="Enable speaker diarization (pyannote — no re-transcription)",
    )
    parser.add_argument("--whisper-device", default=None, choices=["cpu", "cuda"])
    parser.add_argument("--whisper-compute-type", default=None)
    parser.add_argument("--whisper-beam-size", type=int, default=None)

    # LLM
    parser.add_argument(
        "--llm-backend",
        default=None,
        choices=["auto", "ollama", "grok"],
        help="LLM backend (default: auto — uses Grok when XAI_API_KEY is set)",
    )
    parser.add_argument("--ollama-model", default=None)
    parser.add_argument("--grok-model", default=None)
    parser.add_argument(
        "--mode",
        default=None,
        choices=["meeting", "creative", "auto"],
        help="Processing mode (default: meeting)",
    )
    parser.add_argument(
        "--output-format",
        default=None,
        choices=["md", "json", "both"],
        help="Output format for LLM results (default: both)",
    )

    return parser


def resolve_config(args: argparse.Namespace) -> IdeaForgeConfig:
    config_path = args.config
    if config_path is None:
        default = IdeaForgeConfig().default_config_path()
        config_path = default if default.exists() else None

    cfg = IdeaForgeConfig.from_toml(config_path) if config_path else IdeaForgeConfig()
    cfg.resolve_secrets()

    if args.archive:
        cfg.archive = args.archive.expanduser()
    if args.whisper_backend:
        cfg.whisper_backend = args.whisper_backend
    if args.whisper_model:
        cfg.whisper_model = args.whisper_model
    if args.whisper_beam_size is not None:
        cfg.whisper_beam_size = args.whisper_beam_size
    if args.whisper_device:
        cfg.whisper_device = args.whisper_device
    if args.whisper_compute_type:
        cfg.whisper_compute_type = args.whisper_compute_type
    if args.diarize:
        cfg.diarize = True
    if args.llm_backend:
        cfg.llm_backend = args.llm_backend
    if args.ollama_model:
        cfg.ollama_model = args.ollama_model
    if args.grok_model:
        cfg.grok_model = args.grok_model
    if args.mode:
        cfg.mode = args.mode
    if args.output_format:
        cfg.output_format = args.output_format

    cfg.llm_backend = cfg.resolve_llm_backend(cli_override=args.llm_backend)

    return cfg


def resolve_source(args: argparse.Namespace) -> Optional[Path]:
    if args.source:
        return args.source.expanduser().resolve()
    if args.auto_source:
        detected = auto_detect_source()
        if detected:
            print(f"🔍 Auto-detected recorder: {detected}")
            return detected
        print("❌ No recorder auto-detected. Plug in device or use --source.")
        return None
    return None


def main(argv: Optional[list] = None) -> int:
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = resolve_config(args)

    if args.detect:
        devices = find_recorder_mounts()
        if not devices:
            print("No USB recorders detected under /Volumes")
            return 1
        print(f"Found {len(devices)} recorder(s):\n")
        for i, dev in enumerate(devices, 1):
            print(f"[{i}] {dev.label}")
            print(describe_device(dev))
            print()
        return 0

    source = resolve_source(args)
    if source is None:
        parser.error("One of --source or --auto-source is required (unless using --detect)")

    archive = cfg.archive.expanduser().resolve()

    if not source.exists() or not source.is_dir():
        print(f"❌ Source not found: {source}")
        return 1

    extensions: Set[str] = set(cfg.audio_extensions)
    audio_files = get_audio_files(source, extensions, cfg.min_file_size_bytes)

    print(f"🚀 IdeaForge v{__version__}")
    print(f"   Source:  {source}")
    print(f"   Archive: {archive}")
    whisper_backend = resolve_whisper_backend(cfg.whisper_backend)
    print(f"   Mode:    {cfg.mode} | LLM: {cfg.llm_backend} | Output: {cfg.output_format}")
    print(f"   Whisper: {whisper_backend} ({cfg.whisper_model})" + (" + diarize" if cfg.diarize else ""))
    print(f"   Found {len(audio_files)} audio file(s)")

    if args.list_only:
        for f in audio_files:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.name}  ({size_mb:.1f} MB)")
        return 0

    processed_log = load_processed_log(archive)

    newly_processed = 0
    iterator = tqdm(audio_files, desc="Processing") if tqdm else audio_files

    for audio_file in iterator:
        if should_skip_by_hash(audio_file, processed_log) and not args.force:
            print(f"\n⏭️  Skipping {audio_file.name} (already processed)")
            continue

        date_folder = archive_folder_for_file(audio_file, archive)
        print(f"\n📼 {audio_file.name} → {date_folder.name}/")

        process_path = audio_file
        if not args.no_copy:
            process_path = copy_file_safely(audio_file, date_folder)
            print("   📥 Copied to archive")

        transcript_path = None
        if not args.no_transcribe:
            transcript_path = transcribe_audio(
                process_path,
                date_folder,
                whisper_backend=cfg.whisper_backend,
                whisper_model=cfg.whisper_model,
                whisper_device=cfg.whisper_device,
                whisper_compute_type=cfg.whisper_compute_type,
                beam_size=cfg.whisper_beam_size,
                force=args.force,
                diarize=cfg.diarize,
                hf_token=cfg.hf_token,
            )

        if not args.no_llm and transcript_path:
            process_transcript(
                transcript_path,
                date_folder,
                mode=cfg.mode,  # type: ignore[arg-type]
                backend=cfg.llm_backend,
                ollama_model=cfg.ollama_model,
                grok_model=cfg.grok_model,
                output_format=cfg.output_format,
                force=args.force,
            )

        record_processed(processed_log, audio_file, date_folder)
        newly_processed += 1

    save_processed_log(archive, processed_log)
    print(f"\n✅ IdeaForge complete — {newly_processed} file(s) processed")
    return 0


if __name__ == "__main__":
    sys.exit(main())