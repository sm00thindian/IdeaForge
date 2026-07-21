"""Tests for USB recorder daemon watcher."""

import argparse
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from ideaforge.config import IdeaForgeConfig
from ideaforge.daemon import DeviceSnapshot, RecorderWatcher, snapshot_device
from ideaforge.notify import ProcessResult
from ideaforge.device import RecorderDevice
from ideaforge.device_profiles import Z28Profile
from ideaforge.pipeline import PipelineStages


def _device(tmp_path: Path, *, count: int = 1, mtime: float = 1000.0) -> RecorderDevice:
    tmp_path.mkdir(parents=True, exist_ok=True)
    record = tmp_path / "RECORD"
    record.mkdir()
    profile = Z28Profile()
    for i in range(count):
        wav = record / f"R2026-06-27-07-43-{10 + i:02d}.WAV"
        wav.write_bytes(b"\x00" * 1000)
        wav.touch()
    return RecorderDevice(
        mount_path=tmp_path,
        record_folder=record,
        settings_file=None,
        recording_count=count,
        profile_name="z28",
        profile=profile,
    )


def _watcher(**kwargs) -> RecorderWatcher:
    defaults = {
        "cfg": IdeaForgeConfig(),
        "stages": PipelineStages(copy=True, transcribe=True, diarize=False, llm=True),
        "poll_interval": 1.0,
        "settle_seconds": 0.0,
        "sleep_fn": lambda _s: None,
        "process_fn": MagicMock(return_value=ProcessResult(files_processed=1)),
    }
    defaults.update(kwargs)
    return RecorderWatcher(**defaults)


def test_snapshot_device_tracks_count_and_mtime(tmp_path: Path):
    device = _device(tmp_path, count=2)
    snap = snapshot_device(device)
    assert snap.recording_count == 2
    assert snap.newest_mtime > 0


def test_tick_runs_pipeline_on_new_device(tmp_path: Path, monkeypatch):
    device = _device(tmp_path)
    process_fn = MagicMock(return_value=ProcessResult(files_processed=1))
    watcher = _watcher(process_fn=process_fn)

    monkeypatch.setattr(
        "ideaforge.daemon.find_recorder_mounts",
        lambda *args, **kwargs: [device],
    )

    result = watcher.tick()
    assert result.files_processed == 1
    process_fn.assert_called_once()


def test_tick_skips_when_snapshot_unchanged(tmp_path: Path, monkeypatch, capsys):
    device = _device(tmp_path)
    process_fn = MagicMock(return_value=ProcessResult(files_processed=1))
    watcher = _watcher(process_fn=process_fn)

    monkeypatch.setattr(
        "ideaforge.daemon.find_recorder_mounts",
        lambda *args, **kwargs: [device],
    )

    watcher.tick()
    process_fn.reset_mock()
    assert watcher.tick() is None
    assert watcher.tick() is None
    process_fn.assert_not_called()
    out = capsys.readouterr().out
    assert out.count("No new recordings") == 1


def test_tick_logs_idle_once_per_mount(tmp_path: Path, monkeypatch, capsys):
    device = _device(tmp_path)
    watcher = _watcher(process_fn=MagicMock(return_value=ProcessResult(files_processed=1)))

    monkeypatch.setattr(
        "ideaforge.daemon.find_recorder_mounts",
        lambda *args, **kwargs: [device],
    )

    watcher.tick()
    for _ in range(5):
        watcher.tick()
    assert capsys.readouterr().out.count("No new recordings") == 1


def test_tick_runs_when_new_recording_added(tmp_path: Path, monkeypatch):
    device = _device(tmp_path, count=1)
    process_fn = MagicMock(return_value=ProcessResult(files_processed=1))
    watcher = _watcher(process_fn=process_fn)

    monkeypatch.setattr(
        "ideaforge.daemon.find_recorder_mounts",
        lambda *args, **kwargs: [device],
    )
    watcher.tick()
    process_fn.reset_mock()

    (device.record_folder / "R2026-06-27-08-00-00.WAV").write_bytes(b"\x00" * 1000)
    updated = RecorderDevice(
        mount_path=device.mount_path,
        record_folder=device.record_folder,
        settings_file=None,
        recording_count=2,
        profile_name="z28",
        profile=device.profile,
    )
    monkeypatch.setattr(
        "ideaforge.daemon.find_recorder_mounts",
        lambda *args, **kwargs: [updated],
    )

    result = watcher.tick()
    assert result.files_processed == 1
    process_fn.assert_called_once()


def test_tick_skips_multiple_devices(tmp_path: Path, monkeypatch):
    device_a = _device(tmp_path / "a")
    device_b = _device(tmp_path / "b")
    process_fn = MagicMock(return_value=ProcessResult(files_processed=1))
    watcher = _watcher(process_fn=process_fn)

    monkeypatch.setattr(
        "ideaforge.daemon.find_recorder_mounts",
        lambda *args, **kwargs: [device_a, device_b],
    )

    assert watcher.tick() is None
    process_fn.assert_not_called()


def test_daemon_rotates_logs_once_when_due(tmp_path, monkeypatch, capsys):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "daemon.log").write_text("old\n", encoding="utf-8")
    archive = tmp_path / "archive"
    old_merged = archive / "2026-06-20" / "R2026-06-20-09-00-00_merged.wav"
    old_merged.parent.mkdir(parents=True)
    old_merged.write_bytes(b"\x00" * 512)
    os.utime(old_merged, (1_000_000.0, 1_000_000.0))  # far in the past

    times = [
        datetime(2026, 7, 2, 2, 5, 0),
        datetime(2026, 7, 2, 2, 10, 0),
    ]

    def fake_now():
        return times.pop(0) if times else datetime(2026, 7, 2, 2, 15, 0)

    # Patch before constructing the watcher — __init__ loads last-rotated date.
    monkeypatch.setattr("ideaforge.log_util.DEFAULT_LOG_DIR", log_dir)
    monkeypatch.setattr("ideaforge.daemon.load_last_rotated_date", lambda: None)
    monkeypatch.setattr(
        "ideaforge.daemon.find_recorder_mounts",
        lambda *args, **kwargs: [],
    )

    cfg = IdeaForgeConfig(
        archive=archive,
        daemon_log_rotate_enabled=True,
        daemon_log_rotate_hour=2,
        daemon_log_rotate_minute=0,
        daemon_merged_wav_retain_days=3,
    )
    watcher = RecorderWatcher(
        cfg=cfg,
        stages=PipelineStages(copy=True, transcribe=True, diarize=False, llm=True),
        sleep_fn=lambda _s: None,
        process_fn=MagicMock(return_value=ProcessResult()),
        now_fn=fake_now,
    )

    watcher._maybe_rotate_logs()
    watcher._maybe_rotate_logs()
    out = capsys.readouterr().out
    assert out.count("Daily log rotation") == 1
    assert out.count("Pruned 1 merged WAV") == 1
    assert (log_dir / "daemon.log.1").read_text(encoding="utf-8") == "old\n"
    assert not old_merged.exists()


def test_device_snapshot_equality():
    a = DeviceSnapshot("/Volumes/Z29", 3, 1234.5)
    b = DeviceSnapshot("/Volumes/Z29", 3, 1234.5)
    c = DeviceSnapshot("/Volumes/Z29", 4, 1234.5)
    assert a == b
    assert a != c