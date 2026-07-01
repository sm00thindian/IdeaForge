"""Regression: ingest must pass datetime (not DeviceClockInfo) to archive paths."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.config import DeviceBinding, IdeaForgeConfig
from ideaforge.device_registry import discover_mount
from ideaforge.ingest import ingest_device_recordings


def _z28_volume(tmp_path: Path) -> Path:
    volume = tmp_path / "Volumes" / "NO NAME"
    record = volume / "RECORD"
    record.mkdir(parents=True)
    (volume / "recset.txt").write_text("TIME:14:24 2026/7/1\n", encoding="utf-8")
    wav = record / "R2026-06-30-11-27-00.WAV"
    wav.write_bytes(b"\x00" * 60_000)
    return volume


def test_ingest_uses_device_clock_datetime_with_z28_profile(tmp_path: Path):
    volume = _z28_volume(tmp_path)
    archive = tmp_path / "IdeaForge" / "z28"
    cfg = IdeaForgeConfig(
        archive=tmp_path / "IdeaForge",
        devices=[
            DeviceBinding(name="z28", mount_glob="NO NAME", profile="z28"),
        ],
    )
    device = discover_mount(volume, cfg)
    assert device is not None

    with patch("ideaforge.device.is_path_on_recorder", return_value=True):
        result = ingest_device_recordings(
            volume,
            archive,
            cfg,
            delete_after_copy=True,
            device=device,
        )

    assert result.files_copied == 1
    assert result.files_verified == 1
    assert (archive / "2026-07-01" / "R2026-06-30-11-27-00.WAV").is_file()