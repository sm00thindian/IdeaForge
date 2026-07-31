"""Tests for recording datetime resolution."""

from datetime import datetime
from pathlib import Path

from ideaforge.session_time import (
    find_archive_date_folder,
    is_plausible_recording_time,
    reanchor_time_of_day,
    resolve_recording_datetime,
)


def test_resolve_prefers_recset_over_filename(tmp_path: Path):
    path = tmp_path / "R2026-01-15-10-00-00.WAV"
    path.write_bytes(b"x" * 100)
    recset = datetime(2026, 6, 30, 9, 0, 0)
    resolved = resolve_recording_datetime(
        path,
        device_clock=recset,
        reference=datetime(2026, 6, 30, 12, 0, 0),
    )
    assert resolved.source == "recset"
    assert resolved.date_folder == "2026-06-30"


def test_resolve_uses_filename_without_recset(tmp_path: Path):
    path = tmp_path / "R2026-01-15-10-00-00.WAV"
    path.write_bytes(b"x" * 100)
    resolved = resolve_recording_datetime(
        path,
        reference=datetime(2026, 1, 20, 12, 0, 0),
    )
    assert resolved.source == "filename"
    assert resolved.date_folder == "2026-01-15"


def test_resolve_falls_back_to_mtime(tmp_path: Path):
    path = tmp_path / "daily_recording.wav"
    path.write_bytes(b"x" * 100)
    reference = datetime.fromtimestamp(path.stat().st_mtime)
    resolved = resolve_recording_datetime(path, reference=reference)
    assert resolved.source == "mtime"
    assert resolved.date_folder == reference.strftime("%Y-%m-%d")


def test_resolve_skips_implausible_filename_uses_archive_folder(tmp_path: Path):
    """Device battery-reset filenames (e.g. 2014) must not win over archive date."""
    date_folder = tmp_path / "2026-07-31"
    session = date_folder / "V2014-10-06-07-44-57"
    session.mkdir(parents=True)
    path = session / "V2014-10-06-07-44-57.WAV"
    path.write_bytes(b"x" * 100)

    resolved = resolve_recording_datetime(
        path,
        reference=datetime(2026, 7, 31, 13, 0, 0),
    )
    assert resolved.source == "archive"
    assert resolved.date_folder == "2026-07-31"
    assert resolved.dt == datetime(2026, 7, 31, 7, 44, 57)


def test_resolve_skips_implausible_recset_and_filename(tmp_path: Path):
    """When still on device with factory clock, re-anchor time to system day."""
    import os

    path = tmp_path / "V2014-10-06-07-44-57.WAV"
    path.write_bytes(b"x" * 100)
    # mtime also factory-era so we fall through to system re-anchor
    factory = datetime(2014, 10, 6, 7, 44, 57).timestamp()
    os.utime(path, (factory, factory))
    reference = datetime(2026, 7, 31, 12, 0, 0)
    resolved = resolve_recording_datetime(
        path,
        device_clock=datetime(2014, 10, 6, 6, 0, 0),
        reference=reference,
    )
    assert resolved.source == "system"
    assert resolved.date_folder == "2026-07-31"
    assert resolved.dt.hour == 7
    assert resolved.dt.minute == 44


def test_is_plausible_rejects_multi_year_skew():
    ref = datetime(2026, 7, 31, 12, 0, 0)
    assert is_plausible_recording_time(datetime(2026, 7, 1), reference=ref)
    assert is_plausible_recording_time(datetime(2026, 10, 6), reference=ref)
    assert not is_plausible_recording_time(datetime(2014, 10, 6), reference=ref)
    assert not is_plausible_recording_time(datetime(2028, 1, 1), reference=ref)


def test_find_archive_date_folder(tmp_path: Path):
    nested = tmp_path / "z28" / "2026-07-31" / "V2014-10-06-07-44-57"
    nested.mkdir(parents=True)
    wav = nested / "clip.WAV"
    wav.write_bytes(b"x")
    assert find_archive_date_folder(wav) == datetime(2026, 7, 31)


def test_reanchor_time_of_day():
    source = datetime(2014, 10, 6, 7, 44, 57)
    anchor = datetime(2026, 7, 31)
    assert reanchor_time_of_day(source, anchor) == datetime(2026, 7, 31, 7, 44, 57)
