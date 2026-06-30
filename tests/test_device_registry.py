"""Tests for device bindings and per-device archive roots."""

from pathlib import Path

import numpy as np
import wave

from ideaforge.config import DeviceBinding, IdeaForgeConfig
from ideaforge.device_registry import archive_device_root, find_recorder_mounts


def _z28_mount(tmp_path: Path, label: str = "NO NAME") -> Path:
    mount = tmp_path / "Volumes" / label
    record = mount / "RECORD"
    record.mkdir(parents=True)
    wav = record / "R2026-06-30-09-00-00.WAV"
    samples = np.zeros(60_000, dtype=np.int16)
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(12_000)
        wf.writeframes(samples.tobytes())
    return mount


def test_archive_device_root_uses_subdirectory_when_configured(tmp_path: Path):
    cfg = IdeaForgeConfig(
        archive=tmp_path / "IdeaForge",
        devices=[DeviceBinding(name="office-z28", mount_glob="NO NAME", profile="z28")],
    )
    assert archive_device_root(cfg, "office-z28") == tmp_path / "IdeaForge" / "office-z28"
    assert archive_device_root(cfg, None) == tmp_path / "IdeaForge"


def test_find_recorder_mounts_legacy_without_devices_config(tmp_path: Path):
    _z28_mount(tmp_path)
    cfg = IdeaForgeConfig()
    devices = find_recorder_mounts(tmp_path / "Volumes", cfg)
    assert len(devices) == 1
    assert devices[0].profile_name == "z28"
    assert devices[0].device_name is None


def test_find_recorder_mounts_matches_configured_binding(tmp_path: Path):
    _z28_mount(tmp_path, label="NO NAME")
    cfg = IdeaForgeConfig(
        devices=[DeviceBinding(name="office-z28", mount_glob="NO NAME", profile="z28")],
    )
    devices = find_recorder_mounts(tmp_path / "Volumes", cfg)
    assert len(devices) == 1
    assert devices[0].device_name == "office-z28"