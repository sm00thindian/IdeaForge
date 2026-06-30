"""Tests for recording datetime resolution."""

from datetime import datetime
from pathlib import Path

from ideaforge.session_time import resolve_recording_datetime


def test_resolve_prefers_recset_over_filename(tmp_path: Path):
    path = tmp_path / "R2026-01-15-10-00-00.WAV"
    path.write_bytes(b"x" * 100)
    recset = datetime(2026, 6, 30, 9, 0, 0)
    resolved = resolve_recording_datetime(path, device_clock=recset)
    assert resolved.source == "recset"
    assert resolved.date_folder == "2026-06-30"


def test_resolve_uses_filename_without_recset(tmp_path: Path):
    path = tmp_path / "R2026-01-15-10-00-00.WAV"
    path.write_bytes(b"x" * 100)
    resolved = resolve_recording_datetime(path)
    assert resolved.source == "filename"
    assert resolved.date_folder == "2026-01-15"


def test_resolve_falls_back_to_mtime(tmp_path: Path):
    path = tmp_path / "daily_recording.wav"
    path.write_bytes(b"x" * 100)
    resolved = resolve_recording_datetime(path)
    assert resolved.source == "mtime"
    assert resolved.date_folder == datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")