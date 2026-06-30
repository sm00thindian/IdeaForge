"""Tests for USB recorder daemon watcher."""

from pathlib import Path
from unittest.mock import MagicMock

import argparse

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
    result = watcher.tick()
    assert result is None
    process_fn.assert_not_called()
    assert "No new recordings" in capsys.readouterr().out


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


def test_device_snapshot_equality():
    a = DeviceSnapshot("/Volumes/Z29", 3, 1234.5)
    b = DeviceSnapshot("/Volumes/Z29", 3, 1234.5)
    c = DeviceSnapshot("/Volumes/Z29", 4, 1234.5)
    assert a == b
    assert a != c