"""Detect and group consecutive recorder chunks into single sessions."""

from __future__ import annotations

import re
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence

from ideaforge.audio_util import get_audio_duration_seconds

# Z28/Z29: RYYYY-MM-DD-HH-MM-SS.WAV
RECORDING_STEM_PATTERN = re.compile(
    r"^R(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})-"
    r"(?P<hour>\d{2})-(?P<minute>\d{2})-(?P<second>\d{2})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RecordingChunk:
    path: Path
    start: datetime
    duration_seconds: float

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.duration_seconds)


@dataclass(frozen=True)
class RecordingGroup:
    chunks: tuple[RecordingChunk, ...]

    @property
    def files(self) -> List[Path]:
        return [chunk.path for chunk in self.chunks]

    @property
    def session_stem(self) -> str:
        return self.chunks[0].path.stem

    @property
    def label(self) -> str:
        if len(self.chunks) == 1:
            return self.chunks[0].path.name
        first = self.chunks[0].path.name
        last = self.chunks[-1].path.name
        return f"{first} … {last} ({len(self.chunks)} chunks)"

    @property
    def sort_key(self) -> datetime:
        return self.chunks[0].start


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


def _chunk_from_path(path: Path) -> RecordingChunk:
    start = parse_recording_timestamp(path)
    if start is None:
        start = datetime.fromtimestamp(path.stat().st_mtime)
    try:
        duration_seconds = get_audio_duration_seconds(path)
    except (OSError, wave.Error):
        duration_seconds = 0.0
    return RecordingChunk(path=path, start=start, duration_seconds=duration_seconds)


def chunks_are_continuation(
    previous: RecordingChunk,
    next_chunk: RecordingChunk,
    *,
    chunk_gap_seconds: float,
    merge_min_chunk_seconds: float,
) -> bool:
    """
    Return True when ``next_chunk`` likely continues the same session as ``previous``.

    Recorders auto-split long sessions at a fixed max length (e.g. 15 minutes).
    A short prior clip that ends within ``chunk_gap_seconds`` of the next file is
    usually a separate, intentionally stopped recording — not a split segment.
    """
    gap = (next_chunk.start - previous.end).total_seconds()
    if gap < 0 or gap > chunk_gap_seconds:
        return False
    return previous.duration_seconds >= merge_min_chunk_seconds


def group_recordings(
    files: Sequence[Path],
    *,
    enabled: bool = True,
    chunk_gap_seconds: float = 30.0,
    merge_min_chunk_seconds: float = 600.0,
) -> List[RecordingGroup]:
    """
    Group consecutive recorder chunks into one session.

    Chunks belong to the same session when the gap between the end of one file
    and the start of the next is within ``chunk_gap_seconds`` *and* the previous
    chunk is at least ``merge_min_chunk_seconds`` long (indicating a recorder
    auto-split rather than a short, standalone clip).
    """
    if not files:
        return []

    if not enabled:
        return [RecordingGroup(( _chunk_from_path(path),)) for path in files]

    recorder_chunks: List[RecordingChunk] = []
    singletons: List[RecordingChunk] = []

    for path in files:
        chunk = _chunk_from_path(path)
        if parse_recording_timestamp(path) is None:
            singletons.append(chunk)
        else:
            recorder_chunks.append(chunk)

    groups: List[RecordingGroup] = []
    current: List[RecordingChunk] = []

    for chunk in sorted(recorder_chunks, key=lambda item: item.start):
        if not current:
            current = [chunk]
            continue

        if chunks_are_continuation(
            current[-1],
            chunk,
            chunk_gap_seconds=chunk_gap_seconds,
            merge_min_chunk_seconds=merge_min_chunk_seconds,
        ):
            current.append(chunk)
        else:
            groups.append(RecordingGroup(tuple(current)))
            current = [chunk]

    if current:
        groups.append(RecordingGroup(tuple(current)))

    for chunk in sorted(singletons, key=lambda item: item.start):
        groups.append(RecordingGroup((chunk,)))

    groups.sort(key=lambda group: group.sort_key)
    return groups