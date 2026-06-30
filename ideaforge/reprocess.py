"""Re-run the pipeline on archived sessions without hand-editing state."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Sequence, Set

from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import get_audio_files, is_derived_audio
from ideaforge.pipeline import PipelineStages, resolve_stages
from ideaforge.runner import process_source

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

    archive = cfg.archive.expanduser().resolve()
    source = args.source.expanduser().resolve()
    if not source.exists() or not source.is_dir():
        print(f"❌ Source not found: {source}")
        return 1

    scope = collect_reprocess_scope(
        archive,
        source,
        cfg,
        date_from=getattr(args, "reprocess_from", None),
        date_to=getattr(args, "reprocess_to", None),
        session_stems=getattr(args, "reprocess_sessions", None),
    )
    if not scope:
        print("❌ No recordings found to reprocess")
        return 1

    folders = {path.parent.name for path in scope}
    folder_hint = folders.pop() if len(folders) == 1 else f"{len(folders)} date folders"
    print(f"🔄 Reprocessing {len(scope)} file(s) from {folder_hint}")

    stages = resolve_stages(args, cfg).without_copy()
    process_source(
        archive,
        archive,
        cfg,
        stages,
        force=True,
        export_settings=export_settings,
        scope_files=scope,
        include_failed_retries=False,
    )
    return 0