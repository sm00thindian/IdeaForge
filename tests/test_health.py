"""Tests for ideaforge --status health reporting."""

import json
from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.health import (
    ServiceHealth,
    check_daemon_health,
    check_menubar_health,
    collect_status_snapshot,
    format_status_report,
)
from ideaforge.ingest import load_processed_log, record_session_failure, save_processed_log
from ideaforge.status import StatusReporter, STATE_WATCHING


def test_format_status_report_includes_failures(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    log = load_processed_log(archive)
    record_session_failure(
        log,
        session_stem="R2026-06-30-08-00-00",
        archive_folder=archive / "2026-06-30",
        archive_files=[],
        chunk_hashes=[],
        error="transcribe blew up",
        pipeline="copy → transcribe",
    )
    save_processed_log(archive, log)

    cfg = IdeaForgeConfig(archive=archive)
    with (
        patch("ideaforge.health.check_daemon_health") as daemon,
        patch("ideaforge.health.check_menubar_health") as menubar,
        patch("ideaforge.health.find_recorder_mounts", return_value=[]),
        patch("ideaforge.health.load_status") as load_status,
    ):
        daemon.return_value = ServiceHealth(
            label="com.ideaforge.daemon",
            installed=True,
            running=True,
            pid=4242,
        )
        menubar.return_value = ServiceHealth(
            label="com.ideaforge.menubar",
            installed=True,
            running=False,
        )
        reporter = StatusReporter(enabled=False)
        reporter.set_watching()
        load_status.return_value = reporter._status

        report = format_status_report(cfg)

    assert "1 pending" in report
    assert "R2026-06-30-08-00-00" in report
    assert "running (pid 4242)" in report
    assert "stopped (LaunchAgent installed)" in report
    assert "Watching for recorder" in report


def test_collect_status_snapshot_json_shape(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    cfg = IdeaForgeConfig(archive=archive)

    with (
        patch("ideaforge.health.check_daemon_health") as daemon,
        patch("ideaforge.health.check_menubar_health") as menubar,
        patch("ideaforge.health.find_recorder_mounts", return_value=[]),
        patch("ideaforge.health.load_status") as load_status,
    ):
        daemon.return_value = ServiceHealth("com.ideaforge.daemon", True, False)
        menubar.return_value = ServiceHealth("com.ideaforge.menubar", False, False)
        reporter = StatusReporter(enabled=False)
        reporter._status.state = STATE_WATCHING
        load_status.return_value = reporter._status

        snapshot = collect_status_snapshot(cfg)

    assert snapshot["failure_count"] == 0
    assert "pipeline" in snapshot
    assert "services" in snapshot
    assert json.dumps(snapshot)


def test_service_health_status_line():
    assert ServiceHealth("x", False, False).status_line == "not installed"
    assert ServiceHealth("x", True, True, pid=99).status_line == "running (pid 99)"
    assert ServiceHealth("x", True, False).status_line == "stopped (LaunchAgent installed)"


def test_check_daemon_health_uses_pgrep_on_darwin():
    with (
        patch("ideaforge.health._is_darwin", return_value=True),
        patch("ideaforge.health._launch_agent_installed", return_value=True),
        patch("ideaforge.health._pgrep_first", return_value=1234),
    ):
        health = check_daemon_health()
    assert health.running is True
    assert health.pid == 1234