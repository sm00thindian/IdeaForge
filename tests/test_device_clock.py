"""Tests for recorder clock helper."""

from datetime import datetime
from pathlib import Path

from ideaforge.device import (
    RecorderDevice,
    format_device_clock_report,
    format_recset_time_line,
    parse_recset_time,
    read_device_clock,
    run_device_clock,
    sync_device_clock,
    update_recset_time,
)


def test_parse_recset_time_standard_format(tmp_path: Path):
    settings = tmp_path / "recset.txt"
    settings.write_text("BIT:2\nTIME:14:24 2025/7/7\n", encoding="utf-8")
    parsed = parse_recset_time(settings)
    assert parsed == datetime(2025, 7, 7, 14, 24, 0)


def test_parse_recset_time_with_seconds(tmp_path: Path):
    settings = tmp_path / "recset.txt"
    settings.write_text("TIME:09:05:30 2026/06/30\n", encoding="utf-8")
    parsed = parse_recset_time(settings)
    assert parsed == datetime(2026, 6, 30, 9, 5, 30)


def test_read_device_clock_computes_skew(tmp_path: Path):
    settings = tmp_path / "recset.txt"
    settings.write_text("TIME:12:00 2020/1/1\n", encoding="utf-8")
    device = RecorderDevice(
        mount_path=tmp_path,
        record_folder=tmp_path / "RECORD",
        settings_file=settings,
        recording_count=0,
    )
    info = read_device_clock(device)

    assert info is not None
    assert info.device_time == datetime(2020, 1, 1, 12, 0, 0)
    assert info.skew_seconds < 0
    report = format_device_clock_report(info)
    assert "behind system time" in report


def test_format_recset_time_line_z28_style():
    assert format_recset_time_line(datetime(2025, 7, 7, 14, 24, 0)) == "TIME:14:24 2025/7/7"
    assert format_recset_time_line(datetime(2026, 6, 30, 9, 5, 30)) == "TIME:9:05:30 2026/6/30"


def test_update_recset_time_preserves_other_lines(tmp_path: Path):
    settings = tmp_path / "recset.txt"
    settings.write_text("BIT:2\nTIME:12:00 2020/1/1\n", encoding="utf-8")
    new_time = datetime(2026, 6, 30, 15, 30, 0)

    assert update_recset_time(settings, new_time) is True
    assert settings.read_text(encoding="utf-8") == "BIT:2\nTIME:15:30 2026/6/30\n"


def test_sync_device_clock_skips_within_threshold(tmp_path: Path):
    settings = tmp_path / "recset.txt"
    now = datetime.now()
    settings.write_text(
        f"TIME:{now.hour}:{now.minute:02d} {now.year}/{now.month}/{now.day}\n",
        encoding="utf-8",
    )
    device = RecorderDevice(
        mount_path=tmp_path,
        record_folder=tmp_path / "RECORD",
        settings_file=settings,
        recording_count=0,
    )

    result = sync_device_clock(device, max_skew_seconds=60.0)

    assert result.skipped is True
    assert result.updated is False
    assert "threshold" in result.reason


def test_sync_device_clock_updates_when_skewed(tmp_path: Path):
    settings = tmp_path / "recset.txt"
    settings.write_text("TIME:12:00 2020/1/1\n", encoding="utf-8")
    device = RecorderDevice(
        mount_path=tmp_path,
        record_folder=tmp_path / "RECORD",
        settings_file=settings,
        recording_count=0,
    )

    result = sync_device_clock(device, max_skew_seconds=60.0)

    assert result.updated is True
    assert result.previous_time == datetime(2020, 1, 1, 12, 0, 0)
    assert result.new_time is not None
    assert parse_recset_time(settings) == result.new_time


def test_run_device_clock_requires_recset(tmp_path: Path):
    mount = tmp_path / "NO NAME"
    record = mount / "RECORD"
    record.mkdir(parents=True)
    (record / "R2026-06-30-08-00-00.WAV").write_bytes(b"\x00" * 60_000)

    assert run_device_clock(mount) == 1