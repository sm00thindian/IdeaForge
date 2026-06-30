"""Integration: chunk grouping rules + WAV concat produce correct merged sessions."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import wave

from ideaforge.audio_util import concat_wav_files, get_audio_duration_seconds
from ideaforge.chunks import chunks_are_continuation, group_recordings
from ideaforge.chunks import _chunk_from_path


def _write_wav(path: Path, *, duration_seconds: float, sample_rate: int = 12_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.zeros(int(sample_rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


def test_group_then_concat_merged_session_duration(tmp_path: Path):
    """Recorder auto-split: group_recordings + concat_wav_files = one long session."""
    base = datetime(2025, 7, 7, 17, 0, 0)
    chunk_duration = 15 * 60
    paths = []
    for offset_seconds in (0, chunk_duration + 5):
        stamp = (base + timedelta(seconds=offset_seconds)).strftime("R%Y-%m-%d-%H-%M-%S.WAV")
        path = tmp_path / stamp
        _write_wav(path, duration_seconds=chunk_duration)
        paths.append(path)

    groups = group_recordings(
        paths,
        chunk_gap_seconds=30,
        merge_min_chunk_seconds=600,
    )
    assert len(groups) == 1
    assert len(groups[0].files) == 2

    first = _chunk_from_path(groups[0].files[0])
    second = _chunk_from_path(groups[0].files[1])
    assert chunks_are_continuation(
        first,
        second,
        chunk_gap_seconds=30,
        merge_min_chunk_seconds=600,
    )

    merged = concat_wav_files(
        groups[0].files,
        tmp_path / f"{groups[0].session_stem}_merged.WAV",
    )
    expected = chunk_duration * len(groups[0].files)
    actual = get_audio_duration_seconds(merged)
    assert abs(actual - expected) < 0.5


def test_short_clip_not_merged_with_following_session(tmp_path: Path):
    """chunks_are_continuation false → separate groups; no multi-file concat."""
    short = tmp_path / "R2026-06-29-21-10-52.WAV"
    long = tmp_path / "R2026-06-29-21-11-24.WAV"
    _write_wav(short, duration_seconds=20, sample_rate=16_000)
    _write_wav(long, duration_seconds=14 * 60, sample_rate=16_000)

    groups = group_recordings(
        [short, long],
        chunk_gap_seconds=30,
        merge_min_chunk_seconds=600,
    )
    assert len(groups) == 2

    prev = _chunk_from_path(short)
    nxt = _chunk_from_path(long)
    assert not chunks_are_continuation(
        prev,
        nxt,
        chunk_gap_seconds=30,
        merge_min_chunk_seconds=600,
    )

    for group in groups:
        result = concat_wav_files(group.files, tmp_path / f"{group.session_stem}_merged.WAV")
        assert result == group.files[0]