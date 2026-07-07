"""Daemon log rotation helpers."""

from __future__ import annotations

import os
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Optional

DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "ideaforge"
ROTATE_STATE_PATH = Path.home() / ".config" / "ideaforge" / ".log-rotate-date"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
DEFAULT_BACKUPS = 3
DAEMON_LOG_NAMES = ("daemon.log", "daemon.err.log")


def load_last_rotated_date() -> Optional[date]:
    """Return the date logs were last rotated (persisted across daemon restarts)."""
    if not ROTATE_STATE_PATH.is_file():
        return None
    try:
        return date.fromisoformat(ROTATE_STATE_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def save_last_rotated_date(rotated: date) -> None:
    ROTATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROTATE_STATE_PATH.write_text(rotated.isoformat(), encoding="utf-8")


def list_log_files(log_dir: Path | None = None) -> List[Path]:
    """Return active ``*.log`` files (excludes numbered backups like ``daemon.log.1``)."""
    directory = log_dir or DEFAULT_LOG_DIR
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob("*.log")
        if path.is_file() and path.name.endswith(".log")
    )


def is_daily_rotation_due(
    now: datetime,
    *,
    hour: int,
    minute: int,
    last_rotated: Optional[date],
) -> bool:
    """True when local time is past today's schedule and logs were not rotated yet today."""
    if last_rotated == now.date():
        return False
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= scheduled


def rotate_log_file(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    force: bool = False,
) -> bool:
    """
    Rotate ``path`` when it exceeds ``max_bytes`` or when ``force`` is True.

    Returns True when a rotation occurred.
    """
    if backups < 1:
        return False
    if not path.is_file():
        return False
    if not force:
        if max_bytes < 1:
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

    # Copytruncate keeps the inode so launchd stdout/stderr keep writing here.
    backup = path.with_name(f"{path.name}.1")
    shutil.copy2(str(path), str(backup))
    with open(path, "w", encoding="utf-8"):
        pass
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
    """Rotate core daemon log files that exceed the size threshold."""
    directory = log_dir or DEFAULT_LOG_DIR
    rotated: List[Path] = []
    for name in names:
        target = directory / name
        if rotate_log_file(target, max_bytes=max_bytes, backups=backups):
            rotated.append(target)
    return rotated


def rotate_all_logs(
    log_dir: Path | None = None,
    *,
    force: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
) -> List[Path]:
    """Rotate every active ``*.log`` file in the IdeaForge log directory."""
    rotated: List[Path] = []
    for target in list_log_files(log_dir):
        if rotate_log_file(
            target,
            max_bytes=max_bytes,
            backups=backups,
            force=force,
        ):
            rotated.append(target)
    return rotated