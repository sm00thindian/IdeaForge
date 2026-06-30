"""Tests for ideaforge --status health reporting."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from ideaforge.config import DeviceBinding, IdeaForgeConfig
from ideaforge.health import (
    ServiceHealth,
    check_daemon_health,
    check_menubar_health,
    collect_status_snapshot,
    format_status_report,
    open_daemon_log_tail,
    watch_status_report,
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


def test_open_daemon_log_tail_uses_terminal_on_darwin(tmp_path: Path):
    log_path = tmp_path / "daemon.log"
    with (
        patch("ideaforge.health._is_darwin", return_value=True),
        patch("ideaforge.health.subprocess.run") as run,
    ):
        assert open_daemon_log_tail(log_path) is True

    run.assert_called_once()
    cmd = run.call_args.args[0]
    assert cmd[0] == "osascript"
    assert "Terminal" in run.call_args.args[0][2]
    assert "tail -f" in run.call_args.args[0][2]
    assert str(log_path) in run.call_args.args[0][2]


def test_open_daemon_log_tail_falls_back_on_failure(tmp_path: Path):
    log_path = tmp_path / "daemon.log"

    def fake_run(cmd, **kwargs):
        if cmd[0] == "osascript":
            raise subprocess.CalledProcessError(1, "osascript")
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("ideaforge.health._is_darwin", return_value=True),
        patch("ideaforge.health.subprocess.run", side_effect=fake_run) as run,
    ):
        assert open_daemon_log_tail(log_path) is False

    assert run.call_count == 2
    assert run.call_args_list[1].args[0] == ["open", str(log_path.resolve())]


def test_watch_status_report_refreshes_once_before_stop():
    cfg = IdeaForgeConfig()
    calls: list[int] = []

    def fake_print(*_args, **_kwargs) -> None:
        calls.append(1)

    with (
        patch("ideaforge.health.print_status_report", side_effect=fake_print),
        patch("ideaforge.health.time.sleep", side_effect=KeyboardInterrupt),
        patch("ideaforge.health.sys.stdout.isatty", return_value=False),
    ):
        try:
            watch_status_report(cfg, interval=0.1)
        except KeyboardInterrupt:
            pass

    assert len(calls) == 1


def test_format_status_report_aggregates_device_failures(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    z28_root = archive / "z28"
    z28_root.mkdir(parents=True)
    log = load_processed_log(z28_root)
    record_session_failure(
        log,
        session_stem="R2026-06-30-09-00-00",
        archive_folder=z28_root / "2026-06-30",
        archive_files=[],
        chunk_hashes=[],
        error="boom",
        pipeline="test",
    )
    save_processed_log(z28_root, log)

    cfg = IdeaForgeConfig(
        archive=archive,
        devices=[DeviceBinding(name="z28", mount_glob="NO NAME", profile="z28")],
    )
    with (
        patch("ideaforge.health.check_daemon_health") as daemon,
        patch("ideaforge.health.check_menubar_health") as menubar,
        patch("ideaforge.health.find_recorder_mounts", return_value=[]),
        patch("ideaforge.health.load_status") as load_status,
    ):
        daemon.return_value = ServiceHealth("com.ideaforge.daemon", True, False)
        menubar.return_value = ServiceHealth("com.ideaforge.menubar", False, False)
        reporter = StatusReporter(enabled=False)
        reporter.set_watching()
        load_status.return_value = reporter._status

        report = format_status_report(cfg)

    assert "z28/R2026-06-30-09-00-00" in report
    assert "--retry-failed" in report
    assert str(archive / "z28") in report


def test_check_daemon_health_uses_pgrep_on_darwin():
    with (
        patch("ideaforge.health._is_darwin", return_value=True),
        patch("ideaforge.health._launch_agent_installed", return_value=True),
        patch("ideaforge.health._pgrep_first", return_value=1234),
    ):
        health = check_daemon_health()
    assert health.running is True
    assert health.pid == 1234