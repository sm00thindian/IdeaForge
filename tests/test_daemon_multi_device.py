"""Tests for multi-device daemon behavior."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import wave

from ideaforge.config import DeviceBinding, IdeaForgeConfig
from ideaforge.daemon import RecorderWatcher
from ideaforge.device import RecorderDevice
from ideaforge.device_profiles import Z28Profile
from ideaforge.ingest import IngestResult
from ideaforge.notify import ProcessResult
from ideaforge.pipeline import PipelineStages


def _device(tmp_path: Path, label: str, name: str) -> RecorderDevice:
    mount = tmp_path / label
    record = mount / "RECORD"
    record.mkdir(parents=True)
    wav = record / "R2026-06-30-09-00-00.WAV"
    samples = np.zeros(60_000, dtype=np.int16)
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(12_000)
        wf.writeframes(samples.tobytes())
    profile = Z28Profile()
    return RecorderDevice(
        mount_path=mount,
        record_folder=record,
        settings_file=None,
        recording_count=1,
        device_name=name,
        profile_name="z28",
        profile=profile,
    )


def test_watcher_allows_multiple_configured_devices(tmp_path: Path):
    cfg = IdeaForgeConfig(
        archive=tmp_path / "IdeaForge",
        devices=[
            DeviceBinding(name="office", mount_glob="NO NAME", profile="z28"),
            DeviceBinding(name="field", mount_glob="RECORDER", profile="z28"),
        ],
    )
    watcher = RecorderWatcher(
        cfg=cfg,
        stages=PipelineStages(copy=True, transcribe=False, diarize=False, llm=False),
        sleep_fn=lambda _s: None,
    )
    d1 = _device(tmp_path / "mounts", "NO NAME", "office")
    d2 = _device(tmp_path / "mounts", "RECORDER", "field")

    with patch("ideaforge.daemon.find_recorder_mounts", return_value=[d1, d2]):
        with patch.object(watcher, "process_fn", return_value=ProcessResult()) as process:
            watcher.tick()

    process.assert_called_once()
    archive_arg = process.call_args.args[1]
    assert archive_arg == tmp_path / "IdeaForge" / "office"


def test_watcher_rejects_multiple_unconfigured_devices(tmp_path: Path):
    cfg = IdeaForgeConfig()
    watcher = RecorderWatcher(
        cfg=cfg,
        stages=PipelineStages(copy=True, transcribe=False, diarize=False, llm=False),
        sleep_fn=lambda _s: None,
    )
    devices = [
        _device(tmp_path, "A", "a"),
        _device(tmp_path, "B", "b"),
    ]

    with patch("ideaforge.daemon.find_recorder_mounts", return_value=devices):
        with patch.object(watcher, "process_fn") as process:
            result = watcher.tick()

    assert result is None
    process.assert_not_called()