"""Archive layout: date folders hold notes; session subfolders hold recording artifacts.

New layout::

    YYYY-MM-DD/
      20260720 - Meeting title.md     # human-facing notes (date root)
      R2026-07-20-09-00-00/           # per-session package
        R….WAV, R….txt, *_summary.json, ML caches, …

Legacy flat layout (all files as siblings under YYYY-MM-DD/) is still resolved
via dual-path helpers so existing archives keep working without migration.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ideaforge.summary_names import (
    DATE_FOLDER_RE,
    legacy_summary_md_path,
    resolve_summary_md_path,
)

# Session package directories use the recorder stem (or generic file stem).
SESSION_DIR_RE = re.compile(
    r"^R\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}",
    re.IGNORECASE,
)


def is_date_folder(path: Path) -> bool:
    return path.is_dir() and bool(DATE_FOLDER_RE.match(path.name))


def is_session_dir_name(name: str) -> bool:
    """True when ``name`` looks like a session package folder."""
    return bool(SESSION_DIR_RE.match(name)) or (
        not DATE_FOLDER_RE.match(name) and not name.startswith(".")
    )


def session_dir_for(date_folder: Path, session_stem: str) -> Path:
    """Preferred nested path for a session under its date folder."""
    return date_folder / session_stem


def resolve_date_folder(path: Path) -> Optional[Path]:
    """Walk up from ``path`` (file or dir) to the enclosing ``YYYY-MM-DD`` folder."""
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        if DATE_FOLDER_RE.match(candidate.name):
            return candidate
    return None


def resolve_session_dir(date_folder: Path, session_stem: str) -> Path:
    """
    Locate the working directory for a session.

    Prefer the nested package when it exists (or when the date folder itself
    is empty of legacy flat artifacts for this stem). Falls back to the flat
    date folder for legacy archives.
    """
    nested = session_dir_for(date_folder, session_stem)
    if nested.is_dir():
        return nested

    # Legacy flat: artifacts live directly in the date folder.
    if _has_flat_session_artifacts(date_folder, session_stem):
        return date_folder

    # New writes: use nested even if not created yet.
    return nested


def ensure_session_dir(date_folder: Path, session_stem: str) -> Path:
    """Create and return the nested session package directory."""
    target = session_dir_for(date_folder, session_stem)
    target.mkdir(parents=True, exist_ok=True)
    return target


def notes_dir_for_session(session_dir: Path) -> Path:
    """
    Directory where friendly Markdown notes are stored.

    Nested layout → parent date folder. Flat legacy → session_dir itself.
    """
    if is_date_folder(session_dir):
        return session_dir
    parent = session_dir.parent
    if is_date_folder(parent):
        return parent
    return session_dir


def session_artifact_paths(session_dir: Path, stem: str) -> Dict[str, Path]:
    """Standard per-session artifact paths (JSON/txt live in the session dir)."""
    notes_dir = notes_dir_for_session(session_dir)
    resolved_md = resolve_summary_md_path(session_dir, stem)
    if resolved_md is None:
        resolved_md = resolve_summary_md_path(notes_dir, stem)
    return {
        "transcript": session_dir / f"{stem}.txt",
        "summary_md": resolved_md or legacy_summary_md_path(notes_dir, stem),
        "summary_json": session_dir / f"{stem}_summary.json",
        "diarized": session_dir / f"{stem}_diarized.json",
        "segments": session_dir / f"{stem}_segments.json",
        "whisper": session_dir / f"{stem}_whisper.json",
        "turns": session_dir / f"{stem}_turns.json",
        "merged": session_dir / f"{stem}_merged.wav",
        "merged_mp3": session_dir / f"{stem}_merged.mp3",
        "session_dir": session_dir,
        "notes_dir": notes_dir,
        "date_folder": resolve_date_folder(session_dir) or notes_dir,
    }


def _has_flat_session_artifacts(date_folder: Path, session_stem: str) -> bool:
    markers = (
        f"{session_stem}.txt",
        f"{session_stem}_summary.json",
        f"{session_stem}_segments.json",
        f"{session_stem}_whisper.json",
        f"{session_stem}_turns.json",
        f"{session_stem}_diarized.json",
        f"{session_stem}_merged.wav",
        f"{session_stem}_merged.WAV",
        f"{session_stem}_merged.mp3",
        f"{session_stem}.wav",
        f"{session_stem}.WAV",
        f"{session_stem}_summary.md",
    )
    for name in markers:
        if (date_folder / name).is_file():
            return True
    # Hash-collision renames or extra chunks: stem prefix match.
    try:
        for child in date_folder.iterdir():
            if not child.is_file():
                continue
            if child.stem == session_stem or child.stem.startswith(f"{session_stem}_"):
                if child.suffix.lower() in {".wav", ".mp3", ".m4a", ".txt", ".json", ".md"}:
                    return True
    except OSError:
        pass
    return False


def iter_session_dirs(date_folder: Path) -> List[Path]:
    """
    Yield session working directories under a date folder.

    Nested packages first; if the date folder itself still holds flat
    artifacts, include it once for legacy scanning.
    """
    if not date_folder.is_dir():
        return []
    sessions: List[Path] = []
    has_nested = False
    try:
        children = sorted(date_folder.iterdir())
    except OSError:
        return []
    for child in children:
        if child.is_dir() and not child.name.startswith("."):
            # Session packages are non-date dirs under a date folder.
            if not DATE_FOLDER_RE.match(child.name):
                sessions.append(child)
                has_nested = True
    if not has_nested:
        sessions.append(date_folder)
    elif _date_folder_has_loose_artifacts(date_folder):
        # Mid-migration: both nested packages and leftover flat files.
        sessions.append(date_folder)
    return sessions


def _date_folder_has_loose_artifacts(date_folder: Path) -> bool:
    try:
        for child in date_folder.iterdir():
            if not child.is_file() or child.name.startswith("."):
                continue
            # Friendly MD notes at date root are expected — not session artifacts.
            if child.suffix.lower() == ".md" and " - " in child.name:
                continue
            if child.suffix.lower() in {".wav", ".mp3", ".m4a", ".txt", ".json"}:
                return True
            if child.name.endswith("_summary.md"):
                return True
    except OSError:
        return False
    return False


def relocate_files_to_session_dir(
    files: Iterable[Path],
    session_dir: Path,
) -> List[Path]:
    """
    Move files into ``session_dir`` when they are not already there.

    Returns the list of final paths (same order as input). No-op for files
    already inside ``session_dir``.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    session_key = session_dir.resolve()
    result: List[Path] = []
    for path in files:
        try:
            resolved = path.resolve()
        except OSError:
            result.append(path)
            continue
        if resolved.parent == session_key:
            result.append(path)
            continue
        if not path.is_file():
            result.append(path)
            continue
        dest = session_dir / path.name
        if dest.exists() and dest.resolve() != resolved:
            # Keep existing dest; drop the source if identical size is best-effort.
            result.append(dest)
            continue
        try:
            shutil.move(str(path), str(dest))
            result.append(dest)
        except OSError:
            print(f"   ⚠️  Could not move into session folder: {path.name}")
            result.append(path)
    return result


def find_summary_json(date_or_session: Path, session_stem: str) -> Optional[Path]:
    """Locate ``{stem}_summary.json`` in nested or flat layout."""
    candidates = [
        date_or_session / f"{session_stem}_summary.json",
        date_or_session / session_stem / f"{session_stem}_summary.json",
    ]
    date_folder = resolve_date_folder(date_or_session)
    if date_folder is not None:
        candidates.append(date_folder / f"{session_stem}_summary.json")
        candidates.append(date_folder / session_stem / f"{session_stem}_summary.json")
    seen: Set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def iter_summary_json_files(folder: Path) -> List[Path]:
    """Find ``*_summary.json`` under a date folder (nested or flat) or a session dir."""
    if not folder.is_dir():
        return []
    found: List[Path] = []
    # Direct children (flat or session dir)
    found.extend(sorted(folder.glob("*_summary.json")))
    # Nested session packages one level down
    try:
        for child in sorted(folder.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                found.extend(sorted(child.glob("*_summary.json")))
    except OSError:
        pass
    # De-dupe
    seen: Set[str] = set()
    unique: List[Path] = []
    for path in found:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def iter_transcript_files(folder: Path) -> List[Path]:
    """Find session transcript ``.txt`` files (nested or flat) under a date folder."""
    if not folder.is_dir():
        return []
    found: List[Path] = []
    for session in iter_session_dirs(folder):
        if session == folder:
            found.extend(sorted(folder.glob("R*.txt")))
            found.extend(sorted(folder.glob("V*.txt")))
            found.extend(sorted(folder.glob("*.txt")))
        else:
            found.extend(sorted(session.glob("R*.txt")))
            found.extend(sorted(session.glob("V*.txt")))
            found.extend(sorted(session.glob("*.txt")))
    seen: Set[str] = set()
    unique: List[Path] = []
    for path in found:
        if path.name.endswith("_suno.txt") or path.name.endswith("_udio.txt"):
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _session_stem_from_filename(path: Path) -> Optional[str]:
    """Recover the logical session stem from an artifact filename."""
    if path.suffix.lower() == ".md" and " - " in path.name:
        return None  # friendly day-root note
    stem = path.stem
    for suffix in (
        "_summary",
        "_segments",
        "_diarized",
        "_whisper",
        "_turns",
        "_merged",
        "_normalized",
        "_suno",
        "_udio",
    ):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if SESSION_DIR_RE.match(stem) or stem.startswith("R"):
        return stem
    if path.suffix.lower() in {".wav", ".txt", ".json", ".md"} and not stem.startswith("."):
        return stem
    return None


def _infer_session_stems(date_folder: Path) -> List[str]:
    """Infer session stems from loose flat artifacts in a date folder."""
    stems: Set[str] = set()
    try:
        children = list(date_folder.iterdir())
    except OSError:
        return []
    for child in children:
        if child.is_dir():
            continue
        recovered = _session_stem_from_filename(child)
        if recovered:
            stems.add(recovered)
    return sorted(stems)


def _assign_files_to_sessions(date_folder: Path) -> Dict[Path, str]:
    """
    Map each loose file in ``date_folder`` to a session stem.

    Multi-chunk WAV groups (via ``group_recordings``) share the first chunk's
    stem so continuation files land in the same package as ``*_merged.wav``.
    """
    from ideaforge.chunks import group_recordings
    from ideaforge.ingest import is_derived_audio

    assignment: Dict[Path, str] = {}
    try:
        children = [p for p in date_folder.iterdir() if p.is_file()]
    except OSError:
        return assignment

    # 1) Group source WAV chunks so multi-file sessions stay together.
    source_wavs = [
        p
        for p in children
        if p.suffix.lower() == ".wav" and not is_derived_audio(p)
    ]
    if source_wavs:
        for group in group_recordings(source_wavs):
            for path in group.files:
                assignment[path] = group.session_stem
            # Merged artifact belongs with the group stem (one entry on
            # case-insensitive volumes).
            for merged_name in (
                f"{group.session_stem}_merged.wav",
                f"{group.session_stem}_merged.WAV",
                f"{group.session_stem}_merged.mp3",
                f"{group.session_stem}_merged.MP3",
            ):
                merged = date_folder / merged_name
                if merged.is_file():
                    assignment[merged] = group.session_stem
                    break

    # 2) Remaining artifacts (transcripts, JSON, leftover merges, etc.).
    for child in children:
        if child in assignment:
            continue
        if child.suffix.lower() == ".md" and " - " in child.name:
            continue  # friendly day-root notes stay put
        recovered = _session_stem_from_filename(child)
        if recovered:
            assignment[child] = recovered

    return assignment


def migrate_date_folder_to_session_layout(
    date_folder: Path,
    *,
    dry_run: bool = False,
) -> List[tuple[Path, Path]]:
    """
    Move flat date-folder session artifacts into per-session subfolders.

    Friendly ``YYYYMMDD - Title.md`` files stay at the date root.
    Multi-chunk source WAVs are grouped into the first-chunk session package
    (same package as ``*_merged.wav``). Returns list of (source, dest) moves.
    """
    if not is_date_folder(date_folder):
        return []

    moves: List[tuple[Path, Path]] = []
    assignment = _assign_files_to_sessions(date_folder)
    seen_sources: Set[str] = set()
    # Stable order for logging / dry-run.
    for child, stem in sorted(assignment.items(), key=lambda item: str(item[0])):
        if not child.is_file():
            continue
        try:
            source_key = str(child.resolve())
        except OSError:
            source_key = str(child)
        if source_key in seen_sources:
            continue  # case-insensitive FS may list *_merged.wav twice
        seen_sources.add(source_key)

        session_dir = session_dir_for(date_folder, stem)
        dest = session_dir / child.name
        try:
            if dest.exists() and dest.resolve() == child.resolve():
                continue
        except OSError:
            continue
        moves.append((child, dest))
        if not dry_run:
            session_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                continue
            try:
                shutil.move(str(child), str(dest))
            except OSError as exc:
                print(f"   ⚠️  migrate failed {child.name}: {exc}")
    return moves


def migrate_archive_layout(
    root: Path,
    *,
    dry_run: bool = False,
) -> List[tuple[Path, Path]]:
    """Migrate all date folders under ``root`` (device or archive root)."""
    if not root.is_dir():
        return []
    all_moves: List[tuple[Path, Path]] = []
    date_folders: List[Path] = []
    if is_date_folder(root):
        date_folders = [root]
    else:
        try:
            for child in sorted(root.iterdir()):
                if is_date_folder(child):
                    date_folders.append(child)
                elif child.is_dir() and not child.name.startswith("."):
                    # Device subfolder
                    for grand in sorted(child.iterdir()):
                        if is_date_folder(grand):
                            date_folders.append(grand)
        except OSError:
            return []
    for date_folder in date_folders:
        all_moves.extend(
            migrate_date_folder_to_session_layout(date_folder, dry_run=dry_run)
        )
    return all_moves
