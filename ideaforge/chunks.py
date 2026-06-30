"""Detect and group consecutive recorder chunks into single sessions."""

from __future__ import annotations

import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Literal, Optional, Sequence

from ideaforge.audio_util import (
    get_audio_duration_seconds,
    split_audio_by_silence,
    split_audio_fixed_window,
)
from ideaforge.session_time import (
    ResolvedRecordingTime,
    parse_recording_timestamp,
    resolve_recording_datetime,
)

ChunkMode = Literal["gap", "silence", "fixed_window", "none"]


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
    recording_time: Optional[ResolvedRecordingTime] = None

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


def _chunk_from_path(
    path: Path,
    *,
    device_clock: Optional[datetime] = None,
) -> RecordingChunk:
    resolved = resolve_recording_datetime(path, device_clock=device_clock)
    try:
        duration_seconds = get_audio_duration_seconds(path)
    except (OSError, wave.Error, ValueError):
        duration_seconds = 0.0
    return RecordingChunk(path=path, start=resolved.dt, duration_seconds=duration_seconds)


def _group_recording_time(chunks: Sequence[RecordingChunk]) -> ResolvedRecordingTime:
    first = chunks[0]
    return resolve_recording_datetime(first.path)


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
        return [
            RecordingGroup(
                (_chunk_from_path(path),),
                recording_time=_group_recording_time((_chunk_from_path(path),)),
            )
            for path in files
        ]

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
            groups.append(
                RecordingGroup(
                    tuple(current),
                    recording_time=_group_recording_time(current),
                )
            )
            current = [chunk]

    if current:
        groups.append(
            RecordingGroup(
                tuple(current),
                recording_time=_group_recording_time(current),
            )
        )

    for chunk in sorted(singletons, key=lambda item: item.start):
        groups.append(RecordingGroup((chunk,), recording_time=_group_recording_time((chunk,))))

    groups.sort(key=lambda group: group.sort_key)
    return groups


def _should_split_singleton(group: RecordingGroup) -> bool:
    if len(group.chunks) != 1:
        return False
    return parse_recording_timestamp(group.chunks[0].path) is None


def expand_long_recordings(
    groups: List[RecordingGroup],
    *,
    chunk_mode: ChunkMode = "gap",
    split_silence_seconds: float = 3.0,
    split_window_seconds: float = 900.0,
    min_split_duration_seconds: float = 60.0,
) -> List[RecordingGroup]:
    """
    Split non-segmented (non-``R*``) long files into sessions.

    ``chunk_mode``:
    - ``gap`` / ``none`` — no splitting (gap merge handled by ``group_recordings``)
    - ``silence`` — split on silence gaps >= ``split_silence_seconds``
    - ``fixed_window`` — split every ``split_window_seconds``
    """
    if chunk_mode not in ("silence", "fixed_window"):
        return groups

    expanded: List[RecordingGroup] = []
    for group in groups:
        if not _should_split_singleton(group):
            expanded.append(group)
            continue

        source = group.chunks[0].path
        try:
            duration = get_audio_duration_seconds(source)
        except (OSError, wave.Error, ValueError):
            expanded.append(group)
            continue

        if duration < min_split_duration_seconds:
            expanded.append(group)
            continue

        work_dir = source.parent
        if chunk_mode == "silence":
            parts = split_audio_by_silence(
                source,
                work_dir,
                min_silence_seconds=split_silence_seconds,
            )
        else:
            parts = split_audio_fixed_window(
                source,
                work_dir,
                window_seconds=split_window_seconds,
            )

        if len(parts) <= 1:
            expanded.append(group)
            continue

        base_start = group.chunks[0].start
        offset_seconds = 0.0
        for part_path in parts:
            try:
                part_duration = get_audio_duration_seconds(part_path)
            except (OSError, wave.Error, ValueError):
                part_duration = 0.0
            chunk = RecordingChunk(
                path=part_path,
                start=base_start + timedelta(seconds=offset_seconds),
                duration_seconds=part_duration,
            )
            offset_seconds += part_duration
            expanded.append(
                RecordingGroup(
                    (chunk,),
                    recording_time=group.recording_time or _group_recording_time((chunk,)),
                )
            )

    expanded.sort(key=lambda item: item.sort_key)
    return expanded


def prepare_session_groups(
    files: Sequence[Path],
    *,
    merge_chunks: bool = True,
    chunk_mode: ChunkMode = "gap",
    chunk_gap_seconds: float = 30.0,
    merge_min_chunk_seconds: float = 600.0,
    split_silence_seconds: float = 3.0,
    split_window_seconds: float = 900.0,
) -> List[RecordingGroup]:
    """Group recorder chunks and optionally split long non-segmented files."""
    groups = group_recordings(
        files,
        enabled=merge_chunks and chunk_mode == "gap",
        chunk_gap_seconds=chunk_gap_seconds,
        merge_min_chunk_seconds=merge_min_chunk_seconds,
    )
    if chunk_mode == "gap":
        return groups
    if not merge_chunks and chunk_mode != "gap":
        groups = group_recordings(files, enabled=False)
    return expand_long_recordings(
        groups,
        chunk_mode=chunk_mode,
        split_silence_seconds=split_silence_seconds,
        split_window_seconds=split_window_seconds,
    )