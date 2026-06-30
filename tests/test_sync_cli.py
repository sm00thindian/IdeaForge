"""Tests for ideaforge sync manual command."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.sync_cli import _detect_sync_scope, resolve_manual_sync, run_manual_sync


def test_detect_sync_scope_session_date_folder(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    device = archive / "z28"
    session = device / "2026-06-30"
    session.mkdir(parents=True)
    cfg = IdeaForgeConfig(archive=archive)
    assert _detect_sync_scope(session, cfg) == "session"


def test_detect_sync_scope_device_root(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    device = archive / "z28"
    device.mkdir(parents=True)
    cfg = IdeaForgeConfig(archive=archive)
    assert _detect_sync_scope(device, cfg) == "device"


def test_resolve_manual_sync_session_folder(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    device = archive / "z28"
    session = device / "2026-06-30"
    session.mkdir(parents=True)
    cfg = IdeaForgeConfig(archive=archive)
    local, archive_root, device_root, scope = resolve_manual_sync(session, cfg)
    assert scope == "session"
    assert local == session
    assert device_root == device
    assert archive_root == archive


@patch("ideaforge.sync_cli.run_rsync")
def test_run_manual_sync_dry_run(mock_rsync, tmp_path: Path, capsys):
    archive = tmp_path / "IdeaForge"
    session = archive / "2026-06-30"
    session.mkdir(parents=True)
    (session / "notes.md").write_text("x", encoding="utf-8")
    cfg = IdeaForgeConfig(archive=archive, sync_target="user@nas:/backups")

    mock_rsync.return_value = type(
        "R",
        (),
        {"ok": True, "skipped": False, "local_path": str(session), "target": cfg.sync_target},
    )()

    code = run_manual_sync(cfg, session, dry_run=True)
    assert code == 0
    mock_rsync.assert_called_once()
    assert mock_rsync.call_args.kwargs.get("dry_run") is True
    assert "dry-run" in capsys.readouterr().out