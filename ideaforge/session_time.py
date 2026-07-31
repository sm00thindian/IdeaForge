"""Resolve authoritative recording datetime (recset > filename > archive > mtime)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

# Z28/Z29 continuous mode uses R…; voice-activated (VOR) mode uses V….
RECORDING_STEM_PATTERN = re.compile(
    r"^[RV](?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})-"
    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})$",
    re.IGNORECASE,
)
RECORDING_FILENAME_PATTERN = re.compile(
    r"^[RV]\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.WAV$",
    re.IGNORECASE,
)
DATE_FOLDER_PATTERN = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")
# Source clips only (not *_merged.wav / mp3 artifacts).
SOURCE_RECORDING_GLOBS = ("R*.WAV", "R*.wav", "V*.WAV", "V*.wav")
SOURCE_TRANSCRIPT_GLOBS = ("R*.txt", "V*.txt")

# Reject device default-era / battery-reset timestamps (e.g. Z28 → 2014).
# ~13 months still allows a year of backlog while flagging multi-year skew.
DEFAULT_MAX_SKEW_DAYS = 400


def iter_source_recordings(folder: Path):
    """Yield R*/V* source WAV paths under folder (non-recursive)."""
    if not folder.is_dir():
        return
    seen = set()
    for pattern in SOURCE_RECORDING_GLOBS:
        for path in folder.glob(pattern):
            key = path.name.lower()
            if key in seen:
                continue
            seen.add(key)
            yield path


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


def parse_date_folder_name(name: str) -> Optional[datetime]:
    """Parse ``YYYY-MM-DD`` folder name as midnight local time."""
    match = DATE_FOLDER_PATTERN.match(name)
    if not match:
        return None
    parts = {key: int(value) for key, value in match.groupdict().items()}
    try:
        return datetime(parts["year"], parts["month"], parts["day"])
    except ValueError:
        return None


def find_archive_date_folder(path: Path) -> Optional[datetime]:
    """Walk up from ``path`` for an enclosing ``YYYY-MM-DD`` archive folder."""
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        parsed = parse_date_folder_name(candidate.name)
        if parsed is not None:
            return parsed
    return None


def is_plausible_recording_time(
    dt: datetime,
    *,
    reference: Optional[datetime] = None,
    max_skew_days: int = DEFAULT_MAX_SKEW_DAYS,
) -> bool:
    """True when ``dt`` is within ``max_skew_days`` of ``reference`` (default: now)."""
    ref = reference if reference is not None else datetime.now()
    return abs(dt - ref) <= timedelta(days=max_skew_days)


def reanchor_time_of_day(source: datetime, anchor_date: datetime) -> datetime:
    """Keep time-of-day from ``source`` on the calendar day of ``anchor_date``."""
    return anchor_date.replace(
        hour=source.hour,
        minute=source.minute,
        second=source.second,
        microsecond=0,
    )


RecordingDateSource = Literal["recset", "filename", "archive", "mtime", "system"]


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
    reference: Optional[datetime] = None,
    max_skew_days: int = DEFAULT_MAX_SKEW_DAYS,
) -> ResolvedRecordingTime:
    """
    Pick recording datetime using configured priority:

    1. Device ``recset.txt`` clock (when provided at ingest and plausible)
    2. Recorder filename timestamp (``R|VYYYY-MM-DD-HH-MM-SS``) when plausible
    3. Enclosing archive date folder (``YYYY-MM-DD``), re-anchoring filename time-of-day
    4. File modification time when plausible
    5. System time (last resort)

    Implausible timestamps (e.g. device battery reset to 2014) are skipped so notes
    and archive folders do not inherit factory-default dates.
    """
    ref = reference if reference is not None else datetime.now()
    filename_time = parse_recording_timestamp(path)
    archive_date = find_archive_date_folder(path)

    if device_clock is not None and is_plausible_recording_time(
        device_clock, reference=ref, max_skew_days=max_skew_days
    ):
        return ResolvedRecordingTime(device_clock, "recset")

    if filename_time is not None and is_plausible_recording_time(
        filename_time, reference=ref, max_skew_days=max_skew_days
    ):
        return ResolvedRecordingTime(filename_time, "filename")

    if archive_date is not None:
        if filename_time is not None:
            return ResolvedRecordingTime(
                reanchor_time_of_day(filename_time, archive_date),
                "archive",
            )
        return ResolvedRecordingTime(archive_date, "archive")

    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        mtime = None

    if mtime is not None and is_plausible_recording_time(
        mtime, reference=ref, max_skew_days=max_skew_days
    ):
        return ResolvedRecordingTime(mtime, "mtime")

    # Filename had a usable clock time but an absurd date and no archive folder yet
    # (e.g. still on device with factory-default year).
    if filename_time is not None:
        return ResolvedRecordingTime(
            reanchor_time_of_day(filename_time, ref),
            "system",
        )

    return ResolvedRecordingTime(ref.replace(microsecond=0), "system")
