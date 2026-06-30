"""Resolve authoritative recording datetime (recset > filename > mtime)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

RECORDING_STEM_PATTERN = re.compile(
    r"^R(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})-"
    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})$",
    re.IGNORECASE,
)


def parse_recording_timestamp(path: Path) -> Optional[datetime]:
    """Parse recorder filename timestamp, or None for non-recorder names."""
    match = RECORDING_STEM_PATTERN.match(path.stem)
    if not match:
        return None
    parts = {key: int(value) for key, value in match.groupdict().items()}
    return datetime(
        parts["year"],
        parts["month"],
        parts["day"],
        parts["hour"],
        parts["minute"],
        parts["second"],
    )

RecordingDateSource = Literal["recset", "filename", "mtime"]


@dataclass(frozen=True)
class ResolvedRecordingTime:
    """Authoritative calendar date/time for a recording file."""

    dt: datetime
    source: RecordingDateSource

    @property
    def date_folder(self) -> str:
        return self.dt.strftime("%Y-%m-%d")

    @property
    def iso_date(self) -> str:
        return self.date_folder


def resolve_recording_datetime(
    path: Path,
    *,
    device_clock: Optional[datetime] = None,
) -> ResolvedRecordingTime:
    """
    Pick recording datetime using configured priority:

    1. Device ``recset.txt`` clock (when provided at ingest)
    2. Recorder filename timestamp (``RYYYY-MM-DD-HH-MM-SS``)
    3. File modification time
    """
    if device_clock is not None:
        return ResolvedRecordingTime(device_clock, "recset")

    filename_time = parse_recording_timestamp(path)
    if filename_time is not None:
        return ResolvedRecordingTime(filename_time, "filename")

    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return ResolvedRecordingTime(mtime, "mtime")