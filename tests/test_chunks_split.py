"""Tests for non-segmented recording split modes."""

from pathlib import Path
from unittest.mock import patch

import wave

from ideaforge.chunks import expand_long_recordings, prepare_session_groups
from ideaforge.chunks import group_recordings


def _write_wav(path: Path, *, seconds: float = 1.0, rate: int = 16000) -> None:
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames)


def test_expand_long_recordings_fixed_window(tmp_path: Path):
    source = tmp_path / "all_day.wav"
    _write_wav(source, seconds=30.0)
    groups = group_recordings([source])
    assert len(groups) == 1

    part_a = tmp_path / "all_day_part001.wav"
    part_b = tmp_path / "all_day_part002.wav"
    _write_wav(part_a, seconds=15.0)
    _write_wav(part_b, seconds=15.0)

    with patch("ideaforge.chunks.split_audio_fixed_window", return_value=[part_a, part_b]):
        expanded = expand_long_recordings(
            groups,
            chunk_mode="fixed_window",
            split_window_seconds=15.0,
            min_split_duration_seconds=10.0,
        )

    assert len(expanded) == 2
    assert expanded[0].session_stem == "all_day_part001"
    assert expanded[1].session_stem == "all_day_part002"


def test_prepare_session_groups_gap_mode_unchanged(tmp_path: Path):
    first = tmp_path / "R2026-06-30-10-00-00.WAV"
    second = tmp_path / "R2026-06-30-10-14-50.WAV"
    _write_wav(first, seconds=890.0)
    _write_wav(second, seconds=890.0)
    groups = prepare_session_groups(
        [first, second],
        merge_chunks=True,
        chunk_mode="gap",
        chunk_gap_seconds=30,
        merge_min_chunk_seconds=600,
    )
    assert len(groups) == 1
    assert len(groups[0].chunks) == 2