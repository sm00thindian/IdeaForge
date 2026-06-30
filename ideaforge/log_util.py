"""Daemon log rotation helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, List

DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "ideaforge"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
DEFAULT_BACKUPS = 3
DAEMON_LOG_NAMES = ("daemon.log", "daemon.err.log")


def rotate_log_file(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
) -> bool:
    """
    Rotate ``path`` when it exceeds ``max_bytes``.

    Returns True when a rotation occurred.
    """
    if backups < 1 or max_bytes < 1:
        return False
    if not path.is_file():
        return False
    try:
        if path.stat().st_size <= max_bytes:
            return False
    except OSError:
        return False

    oldest = path.with_name(f"{path.name}.{backups}")
    if oldest.exists():
        oldest.unlink()

    for index in range(backups - 1, 0, -1):
        older = path.with_name(f"{path.name}.{index}")
        newer = path.with_name(f"{path.name}.{index + 1}")
        if older.exists():
            shutil.move(str(older), str(newer))

    shutil.move(str(path), str(path.with_name(f"{path.name}.1")))
    path.touch()
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass
    return True


def rotate_daemon_logs(
    log_dir: Path | None = None,
    *,
    names: Iterable[str] = DAEMON_LOG_NAMES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
) -> List[Path]:
    """Rotate daemon log files that exceed the size threshold."""
    directory = log_dir or DEFAULT_LOG_DIR
    rotated: List[Path] = []
    for name in names:
        target = directory / name
        if rotate_log_file(target, max_bytes=max_bytes, backups=backups):
            rotated.append(target)
    return rotated