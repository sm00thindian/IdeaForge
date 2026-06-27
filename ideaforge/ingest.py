"""Audio file discovery, deduplication, and safe copying."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set


def compute_file_hash(file_path: Path, block_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            sha256.update(block)
    return sha256.hexdigest()


def get_audio_files(
    source: Path,
    extensions: Set[str],
    min_size_bytes: int = 50_000,
) -> List[Path]:
    files: List[Path] = []
    normalized = {ext.lower() for ext in extensions} | {ext.upper() for ext in extensions}
    for ext in normalized:
        files.extend(source.rglob(f"*{ext}"))
    valid = [f for f in files if f.is_file() and f.stat().st_size >= min_size_bytes]
    return sorted(valid, key=lambda p: p.stat().st_mtime)


def load_processed_log(archive: Path) -> Dict[str, Any]:
    log_path = archive / ".processed_log.json"
    if log_path.exists():
        try:
            return json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"hashes": [], "files": {}}


def save_processed_log(archive: Path, log: Dict[str, Any]) -> None:
    log_path = archive / ".processed_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def should_skip_by_hash(file_path: Path, processed_log: Dict[str, Any]) -> bool:
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


def record_processed(
    log: Dict[str, Any],
    source_file: Path,
    archive_path: Path,
) -> None:
    file_hash = compute_file_hash(source_file)
    if file_hash not in log["hashes"]:
        log["hashes"].append(file_hash)
    log["files"][file_hash] = {
        "source": str(source_file),
        "archive": str(archive_path),
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    }