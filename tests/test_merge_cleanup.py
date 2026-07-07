"""Tests for post-merge chunk WAV cleanup."""

from pathlib import Path

import numpy as np
import wave

from ideaforge.session_worker import _purge_chunk_sources_after_merge


def _write_wav(path: Path, *, duration_seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12_000
    samples = np.zeros(int(rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_purge_chunk_sources_after_merge(tmp_path: Path):
    folder = tmp_path / "session"
    folder.mkdir()
    chunk_a = folder / "R2026-06-30-09-00-00.WAV"
    chunk_b = folder / "R2026-06-30-09-15-00.WAV"
    merged = folder / "R2026-06-30-09-00-00_merged.wav"
    _write_wav(chunk_a, duration_seconds=2.0)
    _write_wav(chunk_b, duration_seconds=2.0)
    _write_wav(merged, duration_seconds=4.0)

    removed = _purge_chunk_sources_after_merge(
        chunk_paths=[chunk_a, chunk_b],
        pipeline_paths=[chunk_a, chunk_b],
        merged_path=merged,
    )

    assert removed == 2
    assert not chunk_a.exists()
    assert not chunk_b.exists()
    assert merged.is_file()


def test_purge_skips_when_merge_missing(tmp_path: Path):
    chunk = tmp_path / "R2026-06-30-09-00-00.WAV"
    merged = tmp_path / "R2026-06-30-09-00-00_merged.wav"
    _write_wav(chunk)

    removed = _purge_chunk_sources_after_merge(
        chunk_paths=[chunk],
        pipeline_paths=[chunk],
        merged_path=merged,
    )

    assert removed == 0
    assert chunk.is_file()