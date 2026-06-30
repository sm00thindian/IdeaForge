"""Audio file discovery, deduplication, and safe copying."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Set, TYPE_CHECKING

from ideaforge.state_db import (
    ProcessedLog,
    ProcessedLogLike,
    clear_session_failure,
    failed_session_stems,
    load_processed_log,
    normalize_processed_log,
    record_session_failure,
    save_processed_log,
)

if TYPE_CHECKING:
    from ideaforge.config import IdeaForgeConfig


def compute_file_hash(file_path: Path, block_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            sha256.update(block)
    return sha256.hexdigest()


def is_derived_audio(path: Path) -> bool:
    """True for pipeline-generated audio (e.g. merged chunks), not source recordings."""
    return path.stem.endswith("_merged")


def get_audio_files(
    source: Path,
    extensions: Set[str],
    min_size_bytes: int = 50_000,
) -> List[Path]:
    files: List[Path] = []
    normalized = {ext.lower() for ext in extensions} | {ext.upper() for ext in extensions}
    for ext in normalized:
        files.extend(source.rglob(f"*{ext}"))
    valid = [
        f
        for f in files
        if f.is_file()
        and f.stat().st_size >= min_size_bytes
        and not is_derived_audio(f)
    ]
    return sorted(valid, key=lambda p: p.stat().st_mtime)


def should_skip_by_hash(file_path: Path, processed_log: ProcessedLogLike) -> bool:
    try:
        return compute_file_hash(file_path) in processed_log.get("hashes", [])
    except OSError:
        return False


def archive_folder_for_file(audio_file: Path, archive_root: Path) -> Path:
    """Place files in dated folders based on recording mtime."""
    mtime = datetime.fromtimestamp(audio_file.stat().st_mtime)
    return archive_root / mtime.strftime("%Y-%m-%d")


def copy_file_safely(src: Path, dest_folder: Path) -> Path:
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest = dest_folder / src.name
    if dest.exists():
        short_hash = compute_file_hash(src)[:10]
        dest = dest_folder / f"{src.stem}_{short_hash}{src.suffix}"
    shutil.copy2(src, dest)
    return dest


def verify_copy(src: Path, archive_copy: Path) -> bool:
    """Confirm archive copy exists and matches source byte-for-byte."""
    if not src.is_file() or not archive_copy.is_file():
        return False
    try:
        return compute_file_hash(src) == compute_file_hash(archive_copy)
    except OSError:
        return False


def find_archive_copy(
    source: Path,
    archive_root: Path,
    processed_log: Optional[ProcessedLogLike] = None,
) -> Optional[Path]:
    """Locate a local archive file that matches the source recording."""
    try:
        source_hash = compute_file_hash(source)
    except OSError:
        return None

    candidates: List[Path] = []
    if processed_log:
        entry = processed_log.get("files", {}).get(source_hash)
        if entry:
            candidates.append(Path(entry["archive"]))

    dest_folder = archive_folder_for_file(source, archive_root)
    candidates.extend([
        dest_folder / source.name,
        dest_folder / f"{source.stem}_{source_hash[:10]}{source.suffix}",
    ])

    seen: Set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file() and compute_file_hash(candidate) == source_hash:
            return candidate
    return None


def remove_device_file_after_copy(source: Path, archive_copy: Path) -> bool:
    """Delete source from device only after hash-verified archive copy."""
    if not verify_copy(source, archive_copy):
        return False
    source.unlink()
    return True


@dataclass
class IngestResult:
    """Outcome of bulk device ingest (copy → verify → optional purge)."""

    archive_files: List[Path] = field(default_factory=list)
    files_copied: int = 0
    files_verified: int = 0
    files_deleted: int = 0
    files_failed: int = 0

    @property
    def has_work(self) -> bool:
        return bool(self.archive_files)

    @property
    def device_cleared(self) -> bool:
        return self.files_failed == 0


def ingest_device_recordings(
    source: Path,
    archive: Path,
    cfg: "IdeaForgeConfig",
    *,
    delete_after_copy: bool = True,
    reporter: Optional[Any] = None,
) -> IngestResult:
    """
    Copy all recordings from a device mount to the archive, verify hashes,
    then optionally remove verified sources from the device.

    Intended for daemon runs so transcription runs only on local copies.
    """
    from ideaforge.device import is_path_on_recorder
    from ideaforge.status import Stage

    extensions: Set[str] = set(cfg.audio_extensions)
    device_files = get_audio_files(source, extensions, cfg.min_file_size_bytes)
    result = IngestResult()
    if not device_files:
        return result

    processed_log = load_processed_log(archive)
    total = len(device_files)

    print(f"\n📥 Ingesting {total} recording(s) from device → archive")
    if reporter is not None:
        reporter.touch(
            stage=Stage.INGESTING,
            progress=0.0,
            detail=f"0/{total} files copied",
            clear_progress=True,
        )

    for index, audio_file in enumerate(device_files, start=1):
        archive_copy = find_archive_copy(audio_file, archive, processed_log)
        if archive_copy is None:
            dest_folder = archive_folder_for_file(audio_file, archive)
            archive_copy = copy_file_safely(audio_file, dest_folder)
            result.files_copied += 1
            print(f"   📋 Copied {audio_file.name} → {archive_copy.parent.name}/")

        if not verify_copy(audio_file, archive_copy):
            print(f"   ⚠️  Archive copy not verified — kept on device: {audio_file.name}")
            result.files_failed += 1
            if reporter is not None:
                reporter.touch(
                    stage=Stage.INGESTING,
                    progress=index / total,
                    detail=f"{index}/{total} — verify failed for {audio_file.name}",
                )
            continue

        result.files_verified += 1
        result.archive_files.append(archive_copy)

        if delete_after_copy and is_path_on_recorder(audio_file):
            if remove_device_file_after_copy(audio_file, archive_copy):
                result.files_deleted += 1
                print(f"   🗑️  Removed from device: {audio_file.name}")
            else:
                print(f"   ⚠️  Could not remove from device: {audio_file.name}")
                result.files_failed += 1

        if reporter is not None:
            reporter.touch(
                stage=Stage.INGESTING,
                progress=index / total,
                detail=f"{index}/{total} files ingested",
            )

    if result.files_verified:
        print(
            f"   ✓ Ingest complete — {result.files_verified} verified"
            f" ({result.files_deleted} removed from device)"
        )
    return result


def archive_paths_for_failed_sessions(
    log: ProcessedLogLike,
    *,
    min_size_bytes: int = 50_000,
) -> List[Path]:
    """Return archive audio paths for sessions recorded in the failure log."""
    paths: List[Path] = []
    seen: Set[str] = set()
    for entry in normalize_processed_log(log).get("failures", {}).values():
        for path_str in entry.get("archive_files", []):
            candidate = Path(path_str)
            key = str(candidate)
            if key in seen or not candidate.is_file():
                continue
            try:
                if candidate.stat().st_size < min_size_bytes:
                    continue
            except OSError:
                continue
            if is_derived_audio(candidate):
                continue
            seen.add(key)
            paths.append(candidate)
    return sorted(paths, key=lambda p: p.stat().st_mtime)


def expand_scope_files(
    scope_files: Optional[List[Path]],
    log: ProcessedLogLike,
    *,
    min_size_bytes: int = 50_000,
    include_failures: bool = True,
) -> Optional[List[Path]]:
    """Merge explicit scope with failed-session archive paths for retry."""
    if scope_files is None and not include_failures:
        return None
    merged: Set[Path] = set(scope_files or [])
    if include_failures:
        merged.update(
            archive_paths_for_failed_sessions(log, min_size_bytes=min_size_bytes)
        )
    if not merged:
        return scope_files
    return sorted(merged, key=lambda p: p.stat().st_mtime)


def record_processed(
    log: ProcessedLogLike,
    source_file: Path,
    archive_path: Path,
    *,
    archive_file: Optional[Path] = None,
    file_hash: Optional[str] = None,
) -> None:
    normalized = normalize_processed_log(log)
    file_hash = file_hash or compute_file_hash(source_file)
    if file_hash not in normalized["hashes"]:
        normalized["hashes"].append(file_hash)
    normalized["files"][file_hash] = {
        "source": str(source_file),
        "archive": str(archive_file or archive_path),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    }