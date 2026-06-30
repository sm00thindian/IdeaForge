"""Tests for --ingest-only CLI flow."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.daemon import run_device_ingest
from ideaforge.ingest import IngestResult


def _recorder(tmp_path: Path) -> Path:
    mount = tmp_path / "NO NAME"
    record = mount / "RECORD"
    record.mkdir(parents=True)
    (record / "R2026-06-30-08-00-00.WAV").write_bytes(b"\x00" * 60_000)
    return mount


def test_run_device_ingest_unmounts_when_configured(tmp_path: Path):
    mount = _recorder(tmp_path)
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive, daemon_unmount_after_ingest=True)
    ingest = IngestResult(
        archive_files=[archive / "2026-06-30" / "R2026-06-30-08-00-00.WAV"],
        files_verified=1,
        files_deleted=1,
    )

    with (
        patch("ideaforge.daemon.ingest_device_recordings", return_value=ingest),
        patch("ideaforge.ingest.list_device_recordings", return_value=[]),
        patch("ideaforge.daemon.unmount_volume", return_value=True) as unmount,
    ):
        result = run_device_ingest(mount, archive, cfg)

    assert result.files_verified == 1
    unmount.assert_called_once_with(mount)


def test_run_device_ingest_syncs_clock_before_ingest(tmp_path: Path):
    mount = _recorder(tmp_path)
    (mount / "recset.txt").write_text("TIME:12:00 2020/1/1\n", encoding="utf-8")
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive, daemon_sync_device_clock=True)
    ingest = IngestResult(files_verified=1)
    calls: list[str] = []

    def _sync(*_args, **_kwargs):
        calls.append("sync")
        from ideaforge.device import ClockSyncResult

        return ClockSyncResult(updated=True, skipped=False, reason="test")

    with (
        patch("ideaforge.daemon.sync_device_clock", side_effect=_sync),
        patch(
            "ideaforge.daemon.ingest_device_recordings",
            side_effect=lambda *_a, **_k: (calls.append("ingest"), ingest)[1],
        ),
    ):
        run_device_ingest(mount, archive, cfg, unmount_after=False)

    assert calls == ["sync", "ingest"]


def test_run_device_ingest_skips_unmount_when_disabled(tmp_path: Path):
    mount = _recorder(tmp_path)
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive)
    ingest = IngestResult(files_verified=1)

    with (
        patch("ideaforge.daemon.ingest_device_recordings", return_value=ingest),
        patch("ideaforge.daemon.unmount_volume") as unmount,
    ):
        run_device_ingest(mount, archive, cfg, unmount_after=False)

    unmount.assert_not_called()