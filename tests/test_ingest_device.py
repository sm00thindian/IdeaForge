"""Tests for bulk device ingest (daemon copy-first flow)."""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import archive_folder_for_file, ingest_device_recordings


def _recorder_layout(tmp_path: Path) -> tuple[Path, Path]:
    volume = tmp_path / "Volumes" / "RECORDER"
    record = volume / "RECORD"
    record.mkdir(parents=True)
    archive = tmp_path / "IdeaForge"
    return volume, archive


def test_ingest_copies_validates_and_deletes(tmp_path: Path):
    volume, archive = _recorder_layout(tmp_path)
    wav = volume / "RECORD" / "R2026-06-27-07-43-11.WAV"
    wav.write_bytes(b"\x00" * 60_000)

    cfg = IdeaForgeConfig(archive=archive)
    with patch("ideaforge.device.is_path_on_recorder", return_value=True):
        result = ingest_device_recordings(
            volume,
            archive,
            cfg,
            delete_after_copy=True,
        )

    assert result.files_copied == 1
    assert result.files_verified == 1
    assert result.files_deleted == 1
    assert result.device_cleared
    assert not wav.exists()
    assert len(result.archive_files) == 1
    assert result.archive_files[0].is_file()


def test_ingest_keeps_device_on_verify_failure(tmp_path: Path):
    volume, archive = _recorder_layout(tmp_path)
    wav = volume / "RECORD" / "R2026-06-27-07-43-11.WAV"
    wav.write_bytes(b"\x00" * 60_000)

    cfg = IdeaForgeConfig(archive=archive)

    with (
        patch("ideaforge.device.is_path_on_recorder", return_value=True),
        patch("ideaforge.ingest.verify_copy", return_value=False),
    ):
        result = ingest_device_recordings(volume, archive, cfg, delete_after_copy=True)

    assert result.files_failed == 1
    assert not result.device_cleared
    assert wav.exists()


def test_ingest_reuses_existing_archive_copy(tmp_path: Path):
    volume, archive = _recorder_layout(tmp_path)
    wav = volume / "RECORD" / "R2026-06-27-07-43-11.WAV"
    wav.write_bytes(b"\x00" * 60_000)
    mtime = datetime(2026, 6, 27, 7, 43, 11).timestamp()
    os.utime(wav, (mtime, mtime))
    date_folder = archive_folder_for_file(wav, archive)
    date_folder.mkdir(parents=True, exist_ok=True)
    existing = date_folder / wav.name
    existing.write_bytes(wav.read_bytes())

    cfg = IdeaForgeConfig(archive=archive)
    with patch("ideaforge.device.is_path_on_recorder", return_value=True):
        result = ingest_device_recordings(volume, archive, cfg, delete_after_copy=True)

    assert result.files_copied == 0
    assert result.files_verified == 1
    assert result.files_deleted == 1
    assert not wav.exists()