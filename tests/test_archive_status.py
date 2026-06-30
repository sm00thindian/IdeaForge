"""Tests for per-device archive failure aggregation."""

from pathlib import Path

from ideaforge.archive_status import collect_archive_failures, pending_failure_count, retry_failed_hint
from ideaforge.config import DeviceBinding, IdeaForgeConfig
from ideaforge.ingest import load_processed_log, record_session_failure, save_processed_log


def test_pending_failure_count_aggregates_device_archives(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    z28_root = archive / "z28"
    z28_root.mkdir(parents=True)

    log = load_processed_log(z28_root)
    record_session_failure(
        log,
        session_stem="R2026-06-30-08-00-00",
        archive_folder=z28_root / "2026-06-30",
        archive_files=[],
        chunk_hashes=[],
        error="x",
        pipeline="test",
    )
    save_processed_log(z28_root, log)

    cfg = IdeaForgeConfig(
        archive=archive,
        devices=[DeviceBinding(name="z28", mount_glob="NO NAME", profile="z28")],
    )
    assert pending_failure_count(cfg) == 1

    labels, _details, devices = collect_archive_failures(cfg)
    assert labels == ["z28/R2026-06-30-08-00-00"]
    assert devices[0]["name"] == "z28"
    assert devices[0]["failure_count"] == 1


def test_retry_failed_hint_single_device(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(
        archive=archive,
        devices=[DeviceBinding(name="z28", mount_glob="NO NAME", profile="z28")],
    )
    hint = retry_failed_hint(cfg)
    assert str(archive / "z28") in hint
    assert "--retry-failed" in hint