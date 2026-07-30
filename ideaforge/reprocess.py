"""Re-run the pipeline on archived sessions without hand-editing state."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Sequence, Set

from ideaforge.config import IdeaForgeConfig
from ideaforge.device_registry import list_device_archive_roots
from ideaforge.ingest import get_audio_files, is_derived_audio
from ideaforge.pipeline import PipelineStages, resolve_stages
from ideaforge.runner import process_source
from ideaforge.session_layout import iter_transcript_files, resolve_date_folder
from ideaforge.session_time import RECORDING_STEM_PATTERN

DATE_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RECORDING_STEM_RE = re.compile(r"^R\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}", re.IGNORECASE)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _date_folders_under(root: Path) -> List[Path]:
    folders: List[Path] = []
    if not root.is_dir():
        return folders
    for child in sorted(root.iterdir()):
        if child.is_dir() and DATE_FOLDER_RE.match(child.name):
            folders.append(child)
    return folders


def resolve_reprocess_folders(
    archive: Path,
    source: Path,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Path]:
    """Resolve archive date folders to scan for reprocessing."""
    archive = archive.expanduser().resolve()
    source = source.expanduser().resolve()

    if source == archive:
        folders = _date_folders_under(archive)
    elif DATE_FOLDER_RE.match(source.name):
        folders = [source]
    elif resolve_date_folder(source) is not None:
        # Session package or file under a date folder → that date folder.
        date_folder = resolve_date_folder(source)
        folders = [date_folder] if date_folder is not None else [source]
    elif archive in source.parents or source.parent == archive:
        folders = [source]
    else:
        folders = [source]

    if date_from or date_to:
        start = _parse_date(date_from) if date_from else date.min
        end = _parse_date(date_to) if date_to else date.max
        filtered: List[Path] = []
        for folder in folders:
            if not DATE_FOLDER_RE.match(folder.name):
                continue
            folder_date = _parse_date(folder.name)
            if start <= folder_date <= end:
                filtered.append(folder)
        folders = filtered

    return folders


def _matches_session_stem(path: Path, session_stems: Sequence[str]) -> bool:
    for stem in session_stems:
        if path.stem == stem or path.name.startswith(f"{stem}."):
            return True
        if path.stem.startswith(f"{stem}_"):
            return True
    return False


def _recording_stem(path: Path) -> Optional[str]:
    match = RECORDING_STEM_RE.match(path.stem)
    if not match:
        return None
    return match.group(0)


def resolve_archive_root_for_source(cfg: IdeaForgeConfig, source: Path) -> Path:
    """Pick the archive root that owns ``source`` (device subfolders, processed log)."""
    resolved = source.expanduser().resolve()
    archive = cfg.archive.expanduser().resolve()

    best: Optional[Path] = None
    for _, device_root in list_device_archive_roots(cfg):
        device_resolved = device_root.resolve()
        if resolved == device_resolved or device_resolved in resolved.parents:
            if best is None or len(str(device_resolved)) > len(str(best)):
                best = device_resolved
    if best is not None:
        return best

    for parent in [resolved, *resolved.parents]:
        if (parent / ".processed_log.json").is_file():
            return parent
        if parent == archive:
            break
    return archive


def collect_reprocess_transcript_scope(
    archive: Path,
    source: Path,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    session_stems: Optional[Sequence[str]] = None,
) -> List[Path]:
    """Collect transcript ``.txt`` files when source audio has already been removed."""
    folders = resolve_reprocess_folders(
        archive,
        source,
        date_from=date_from,
        date_to=date_to,
    )
    files: List[Path] = []
    seen: Set[str] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in iter_transcript_files(folder):
            if not RECORDING_STEM_PATTERN.match(path.stem):
                # Still allow non-R* transcripts that are real session stems.
                if path.suffix.lower() != ".txt":
                    continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(path)

    if session_stems:
        normalized = [stem.strip() for stem in session_stems if stem.strip()]
        files = [
            path
            for path in files
            if _matches_session_stem(path, normalized)
            or (_recording_stem(path) in normalized)
        ]
    return files


def collect_reprocess_scope(
    archive: Path,
    source: Path,
    cfg: IdeaForgeConfig,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    session_stems: Optional[Sequence[str]] = None,
) -> List[Path]:
    """Collect archive audio files to include in a reprocess run."""
    extensions: Set[str] = set(cfg.audio_extensions)
    folders = resolve_reprocess_folders(
        archive,
        source,
        date_from=date_from,
        date_to=date_to,
    )

    files: List[Path] = []
    seen: Set[str] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        for audio_file in get_audio_files(folder, extensions, cfg.min_file_size_bytes):
            key = str(audio_file.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(audio_file)

    if session_stems:
        normalized = [stem.strip() for stem in session_stems if stem.strip()]
        files = [
            path
            for path in files
            if _matches_session_stem(path, normalized)
            or (_recording_stem(path) in normalized)
        ]

    return sorted(files, key=lambda p: p.stat().st_mtime)


def run_reprocess(
    cfg: IdeaForgeConfig,
    args: argparse.Namespace,
    *,
    export_settings=None,
) -> int:
    """Re-run pipeline on archived sessions (implies force, no copy)."""
    if not args.source:
        raise ValueError("--reprocess requires --source")

    source = args.source.expanduser().resolve()
    if not source.exists() or not source.is_dir():
        print(f"❌ Source not found: {source}")
        return 1

    archive = resolve_archive_root_for_source(cfg, source)
    session_stems = getattr(args, "reprocess_sessions", None)
    date_from = getattr(args, "reprocess_from", None)
    date_to = getattr(args, "reprocess_to", None)

    scope = collect_reprocess_scope(
        archive,
        source,
        cfg,
        date_from=date_from,
        date_to=date_to,
        session_stems=session_stems,
    )
    stages = resolve_stages(args, cfg).without_copy()
    if not scope and stages.llm and not stages.transcribe:
        scope = collect_reprocess_transcript_scope(
            archive,
            source,
            date_from=date_from,
            date_to=date_to,
            session_stems=session_stems,
        )
    if not scope:
        print("❌ No recordings found to reprocess")
        print(
            "   Tip: audio may already be processed — try "
            "`ideaforge --rename-summaries --source <folder>` for friendly markdown names, "
            "or `--reprocess --llm-only` when transcripts remain."
        )
        return 1

    folders = {path.parent.name for path in scope}
    folder_hint = folders.pop() if len(folders) == 1 else f"{len(folders)} date folders"
    kind = "transcript(s)" if scope[0].suffix.lower() == ".txt" else "file(s)"
    print(f"🔄 Reprocessing {len(scope)} {kind} from {folder_hint}")

    process_source(
        source,
        archive,
        cfg,
        stages,
        force=True,
        export_settings=export_settings,
        scope_files=scope,
        include_failed_retries=False,
    )
    return 0