"""IdeaForge CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from ideaforge import __version__
from ideaforge.config import IdeaForgeConfig, load_dotenv
from ideaforge.device import (
    auto_detect_source,
    describe_device,
    find_recorder_mounts,
    is_path_on_recorder,
)
from ideaforge.ingest import get_audio_files
from ideaforge.pipeline import resolve_stages
from ideaforge.runner import process_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ideaforge",
        description="IdeaForge — Local-first pipeline for USB voice recorders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  ideaforge --auto-source                          # full pipeline
  ideaforge --daemon                               # watch for USB recorder
  ideaforge --source ~/IdeaForge/2026-06-27 --llm-only --force
  ideaforge --source ~/IdeaForge/2026-06-27 --diarize-only --no-copy
  ideaforge --auto-source --transcribe-only
  ideaforge --auto-source --ingest-only
  ideaforge --source ~/IdeaForge --retry-failed
  ideaforge --reprocess --source ~/IdeaForge/2026-06-27
  ideaforge --reprocess --source ~/IdeaForge --from 2026-06-25 --to 2026-06-30
  ideaforge device clock
  ideaforge --validate-config
  ideaforge --status
  ideaforge --status --watch
  ideaforge --source /Volumes/Z29 --mode meeting --diarize
""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    device_parser = subparsers.add_parser("device", help="USB recorder utilities")
    device_subparsers = device_parser.add_subparsers(dest="device_action", required=True)
    device_clock_parser = device_subparsers.add_parser(
        "clock",
        help="Compare recset.txt clock to system time",
    )
    device_clock_parser.add_argument(
        "--source",
        type=Path,
        help="Recorder mount path (default: auto-detect sole device)",
    )
    device_clock_parser.add_argument(
        "--sync",
        action="store_true",
        help="Write system time to recset.txt when skew exceeds threshold",
    )
    device_clock_parser.add_argument(
        "--force",
        action="store_true",
        help="With --sync: update even when within skew threshold",
    )

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source", type=Path, help="Mounted recorder or folder path")
    source.add_argument(
        "--auto-source",
        action="store_true",
        help="Auto-detect USB recorder under /Volumes",
    )
    source.add_argument(
        "--daemon",
        action="store_true",
        help="Run as background watcher — process when USB recorder is plugged in",
    )

    parser.add_argument("--archive", type=Path, default=None, help="Archive root")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.toml")
    parser.add_argument(
        "--daemon-interval",
        type=float,
        default=None,
        help="Seconds between device polls in daemon mode (default: 5)",
    )
    parser.add_argument(
        "--daemon-settle",
        type=float,
        default=None,
        help="Seconds to wait after mount before processing (default: 5)",
    )

    # Pipeline stages
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument(
        "--transcribe-only",
        action="store_true",
        help="Copy + transcribe only (skip diarize and LLM)",
    )
    stage.add_argument(
        "--diarize-only",
        action="store_true",
        help="Diarize existing transcript (requires _segments.json; skip transcribe)",
    )
    stage.add_argument(
        "--llm-only",
        action="store_true",
        help="Summarize existing transcript only (skip copy, transcribe, diarize)",
    )
    stage.add_argument(
        "--ingest-only",
        action="store_true",
        help="Copy, verify, and purge device files only (no transcribe/LLM)",
    )

    parser.add_argument("--no-copy", action="store_true", help="Skip copying to archive")
    parser.add_argument(
        "--no-unmount",
        action="store_true",
        help="With --ingest-only, skip unmount after successful ingest",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Process only sessions that failed in a prior run",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Re-run pipeline on archived sessions (--source required; implies --force, no copy)",
    )
    parser.add_argument(
        "--from",
        dest="reprocess_from",
        metavar="DATE",
        help="With --reprocess: start date YYYY-MM-DD (archive root source)",
    )
    parser.add_argument(
        "--to",
        dest="reprocess_to",
        metavar="DATE",
        help="With --reprocess: end date YYYY-MM-DD (archive root source)",
    )
    parser.add_argument(
        "--session",
        dest="reprocess_sessions",
        action="append",
        metavar="STEM",
        help="With --reprocess: limit to session stem (repeatable)",
    )
    parser.add_argument("--no-transcribe", action="store_true", help="Skip transcription")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM summarization")
    parser.add_argument("--force", action="store_true", help="Reprocess even if outputs exist")
    parser.add_argument("--list-only", action="store_true", help="List audio files and exit")
    parser.add_argument("--detect", action="store_true", help="Show detected recorders and exit")
    parser.add_argument(
        "--device-clock",
        action="store_true",
        help="Compare recorder recset.txt clock to system time (alias for device clock)",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate config.toml and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show pipeline progress, service health, and pending failures",
    )
    parser.add_argument(
        "--status-json",
        action="store_true",
        help="Emit --status output as JSON (for scripting)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="With --status, refresh periodically until Ctrl+C",
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=2.0,
        help="Seconds between --status --watch refreshes (default: 2)",
    )

    parser.add_argument(
        "--whisper-model",
        default=None,
        choices=["tiny", "base", "small", "medium", "large-v3"],
    )
    parser.add_argument(
        "--whisper-backend",
        default=None,
        choices=["auto", "mlx", "faster"],
    )
    parser.add_argument("--diarize", action="store_true", help="Enable speaker diarization")
    parser.add_argument("--whisper-device", default=None, choices=["cpu", "cuda"])
    parser.add_argument("--whisper-compute-type", default=None)
    parser.add_argument("--whisper-beam-size", type=int, default=None)
    parser.add_argument(
        "--whisper-language",
        default=None,
        help="Force transcription language (e.g. en); default auto-detect",
    )
    parser.add_argument("--min-speakers", type=int, default=None, help="pyannote min speakers")
    parser.add_argument("--max-speakers", type=int, default=None, help="pyannote max speakers")

    parser.add_argument(
        "--llm-backend",
        default=None,
        choices=["auto", "ollama", "grok", "claude"],
    )
    parser.add_argument("--ollama-model", default=None)
    parser.add_argument("--grok-model", default=None)
    parser.add_argument("--claude-model", default=None)
    parser.add_argument("--mode", default=None, choices=["meeting", "creative", "auto"])
    parser.add_argument("--output-format", default=None, choices=["md", "json", "both"])

    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Export action items from existing *_summary.json files (requires --source)",
    )
    parser.add_argument(
        "--export-reminders",
        action="store_true",
        help="Export action items to Apple Reminders (macOS)",
    )
    parser.add_argument(
        "--export-obsidian",
        action="store_true",
        help="Append action items to an Obsidian note",
    )
    parser.add_argument("--no-export", action="store_true", help="Skip action item export")

    return parser


def resolve_export_settings(cfg: IdeaForgeConfig, args: argparse.Namespace):
    from ideaforge.export import ExportSettings

    settings = cfg.export_settings(force=args.force)
    if args.no_export:
        return ExportSettings()
    if args.export_reminders:
        settings.reminders = True
    if args.export_obsidian:
        settings.obsidian = True
    return settings


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
    if args.whisper_language:
        cfg.whisper_language = args.whisper_language
    if args.whisper_device:
        cfg.whisper_device = args.whisper_device
    if args.whisper_compute_type:
        cfg.whisper_compute_type = args.whisper_compute_type
    if args.diarize:
        cfg.diarize = True
    if args.min_speakers is not None:
        cfg.min_speakers = args.min_speakers
    if args.max_speakers is not None:
        cfg.max_speakers = args.max_speakers
    if args.llm_backend:
        cfg.llm_backend = args.llm_backend
    if args.ollama_model:
        cfg.ollama_model = args.ollama_model
    if args.grok_model:
        cfg.grok_model = args.grok_model
    if args.claude_model:
        cfg.claude_model = args.claude_model
    if args.mode:
        cfg.mode = args.mode
    if args.output_format:
        cfg.output_format = args.output_format
    if args.daemon_interval is not None:
        cfg.daemon_poll_interval = args.daemon_interval
    if args.daemon_settle is not None:
        cfg.daemon_settle_seconds = args.daemon_settle

    return cfg


def resolve_source(args: argparse.Namespace, cfg: IdeaForgeConfig) -> Optional[Path]:
    if args.source:
        return args.source.expanduser().resolve()
    if args.auto_source:
        detected = auto_detect_source(cfg=cfg)
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

    if args.command == "device" and args.device_action == "clock":
        from ideaforge.device import run_device_clock

        return run_device_clock(
            getattr(args, "source", None),
            sync=getattr(args, "sync", False),
            force_sync=getattr(args, "force", False),
        )

    if args.device_clock:
        from ideaforge.device import run_device_clock

        return run_device_clock(args.source)

    if args.validate_config:
        from ideaforge.config_validate import ConfigValidationError, validate_config_file

        path = args.config or IdeaForgeConfig().default_config_path()
        try:
            validate_config_file(path)
        except ConfigValidationError as exc:
            print(f"❌ Invalid config ({path}):\n{exc}")
            return 1
        print(f"✓ Config OK — {path}")
        return 0

    if args.detect:
        devices = find_recorder_mounts(cfg=cfg)
        if not devices:
            print("No USB recorders detected under /Volumes")
            return 1
        print(f"Found {len(devices)} recorder(s):\n")
        for i, dev in enumerate(devices, 1):
            print(f"[{i}] {dev.label}")
            print(describe_device(dev))
            print()
        return 0

    if args.watch and not (args.status or args.status_json):
        parser.error("--watch requires --status or --status-json")

    if args.status or args.status_json:
        from ideaforge.health import print_status_report, watch_status_report

        if args.watch:
            watch_status_report(
                cfg,
                interval=args.watch_interval,
                as_json=args.status_json,
            )
        else:
            print_status_report(cfg, as_json=args.status_json)
        return 0

    if args.daemon:
        from ideaforge.daemon import run_daemon

        config_path = args.config
        if config_path is None:
            default = IdeaForgeConfig().default_config_path()
            config_path = default if default.exists() else None

        return run_daemon(
            cfg,
            args,
            poll_interval=args.daemon_interval,
            settle_seconds=args.daemon_settle,
            config_path=config_path,
        )

    archive = cfg.archive.expanduser().resolve()

    if args.ingest_only:
        source = resolve_source(args, cfg)
        if source is None:
            parser.error("--ingest-only requires --source or --auto-source")
        if not source.exists() or not source.is_dir():
            print(f"❌ Source not found: {source}")
            return 1
        if not is_path_on_recorder(source):
            print("❌ --ingest-only requires a USB recorder mount (use --auto-source)")
            return 1

        from ideaforge.daemon import run_device_ingest

        ingest = run_device_ingest(
            source,
            archive,
            cfg,
            unmount_after=not args.no_unmount,
        )
        if ingest.files_failed:
            return 1
        print(
            f"\n✅ Ingest complete — {ingest.files_verified} verified, "
            f"{ingest.files_deleted} removed from device"
        )
        return 0

    if args.reprocess:
        from ideaforge.reprocess import run_reprocess

        return run_reprocess(
            cfg,
            args,
            export_settings=resolve_export_settings(cfg, args),
        )

    if args.export_only:
        if not args.source:
            parser.error("--export-only requires --source pointing to a folder with summaries")
        from ideaforge.export import export_summaries_in_folder

        source = args.source.expanduser().resolve()
        if not source.is_dir():
            print(f"❌ Source not found: {source}")
            return 1
        settings = resolve_export_settings(cfg, args)
        if not settings.reminders and not settings.obsidian:
            print("❌ Enable export in config.toml [export] or use --export-reminders / --export-obsidian")
            return 1
        count = export_summaries_in_folder(source, archive, settings)
        print(f"\n✅ Export complete — {count} action item(s) exported")
        return 0

    stages = resolve_stages(args, cfg)
    source = resolve_source(args, cfg)
    if source is None:
        parser.error("One of --source, --auto-source, or --daemon is required (unless using --detect)")

    if not source.exists() or not source.is_dir():
        print(f"❌ Source not found: {source}")
        return 1

    if args.list_only:
        extensions = set(cfg.audio_extensions)
        audio_files = get_audio_files(source, extensions, cfg.min_file_size_bytes)
        print(f"Found {len(audio_files)} audio file(s) in {source}")
        for f in audio_files:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.name}  ({size_mb:.1f} MB)")
        return 0

    if args.retry_failed:
        if args.auto_source:
            print("❌ --retry-failed requires --source pointing at the archive root or session folder")
            return 1
        if args.source is None:
            source = archive

    process_source(
        source,
        archive,
        cfg,
        stages,
        force=args.force,
        export_settings=resolve_export_settings(cfg, args),
        retry_failed_only=args.retry_failed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())