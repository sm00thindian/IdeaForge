"""Tests for remote archive sync."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.remote_sync import (
    SyncSettings,
    load_sync_log,
    maybe_sync_after_notes,
    resolve_sync_paths,
    run_rsync,
)


def test_resolve_sync_paths_scopes():
    work = Path("/archive/z28/2026-06-30")
    device = Path("/archive/z28")
    archive = Path("/archive")
    assert resolve_sync_paths(
        work_folder=work,
        archive_root=archive,
        device_root=device,
        scope="session",
    ) == work
    assert resolve_sync_paths(
        work_folder=work,
        archive_root=archive,
        device_root=device,
        scope="device",
    ) == device
    assert resolve_sync_paths(
        work_folder=work,
        archive_root=archive,
        device_root=device,
        scope="archive",
    ) == archive


def test_maybe_sync_after_notes_skips_without_summary(tmp_path: Path):
    work = tmp_path / "2026-06-30"
    work.mkdir()
    settings = SyncSettings(enabled=True, target="user@nas:/backups")
    result = maybe_sync_after_notes(
        work_folder=work,
        archive_root=tmp_path,
        device_root=tmp_path,
        session_stem="R2026-06-30-10-00-00",
        settings=settings,
    )
    assert result.skipped is True


@patch("ideaforge.remote_sync.subprocess.run")
def test_run_rsync_success(mock_run, tmp_path: Path):
    local = tmp_path / "2026-06-30"
    local.mkdir()
    (local / "R2026-06-30-10-00-00_summary.md").write_text("# Notes", encoding="utf-8")
    settings = SyncSettings(enabled=True, target="user@nas:/backups")

    with patch("ideaforge.remote_sync.rsync_available", return_value=True):
        result = run_rsync(local, settings)

    assert result.ok is True
    mock_run.assert_called_once()


def test_maybe_sync_after_notes_records_log(tmp_path: Path):
    work = tmp_path / "2026-06-30"
    work.mkdir()
    (work / "session_summary.json").write_text("{}", encoding="utf-8")
    settings = SyncSettings(enabled=True, target="user@nas:/backups", scope="session")

    with (
        patch("ideaforge.remote_sync.rsync_available", return_value=True),
        patch("ideaforge.remote_sync.run_rsync") as mock_sync,
    ):
        mock_sync.return_value = type(
            "R",
            (),
            {"ok": True, "skipped": False, "local_path": str(work), "target": settings.target},
        )()
        maybe_sync_after_notes(
            work_folder=work,
            archive_root=tmp_path,
            device_root=tmp_path,
            session_stem="session",
            settings=settings,
        )

    log = load_sync_log(tmp_path)
    assert log["synced"]