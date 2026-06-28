"""Tests for recorder chunk grouping."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import wave

from ideaforge.chunks import (
    RecordingGroup,
    group_recordings,
    parse_recording_timestamp,
)


def _write_wav(path: Path, *, duration_seconds: float, sample_rate: int = 12000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.zeros(int(sample_rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


def test_parse_recording_timestamp():
    ts = parse_recording_timestamp(Path("R2025-07-07-17-00-00.WAV"))
    assert ts == datetime(2025, 7, 7, 17, 0, 0)
    assert parse_recording_timestamp(Path("meeting.wav")) is None


def test_group_recordings_merges_consecutive_chunks(tmp_path: Path):
    base = datetime(2025, 7, 7, 17, 0, 0)
    files = []
    for index, minute in enumerate((0, 15, 30)):
        name = (base + timedelta(minutes=minute)).strftime("R%Y-%m-%d-%H-%M-%S.WAV")
        path = tmp_path / name
        _write_wav(path, duration_seconds=15 * 60)
        files.append(path)

    groups = group_recordings(files, chunk_gap_seconds=30)
    assert len(groups) == 1
    assert len(groups[0].files) == 3
    assert groups[0].session_stem == "R2025-07-07-17-00-00"


def test_group_recordings_splits_separate_sessions(tmp_path: Path):
    first = tmp_path / "R2025-07-07-17-00-00.WAV"
    second = tmp_path / "R2025-07-07-18-30-00.WAV"
    _write_wav(first, duration_seconds=10 * 60)
    _write_wav(second, duration_seconds=10 * 60)

    groups = group_recordings([second, first], chunk_gap_seconds=30)
    assert len(groups) == 2
    assert [len(group.files) for group in groups] == [1, 1]


def test_group_recordings_disabled(tmp_path: Path):
    first = tmp_path / "R2025-07-07-17-00-00.WAV"
    second = tmp_path / "R2025-07-07-17-15-00.WAV"
    _write_wav(first, duration_seconds=15 * 60)
    _write_wav(second, duration_seconds=15 * 60)

    groups = group_recordings([first, second], enabled=False)
    assert len(groups) == 2
    assert all(isinstance(group, RecordingGroup) for group in groups)