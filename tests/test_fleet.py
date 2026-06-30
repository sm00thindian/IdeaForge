"""Tests for fleet dashboard snapshot."""

import json
from pathlib import Path
from unittest.mock import patch

from ideaforge.config import DeviceBinding, IdeaForgeConfig
from ideaforge.fleet import collect_fleet_snapshot, format_fleet_report, render_fleet_html
from ideaforge.health import ServiceHealth
from ideaforge.status import StatusReporter


def test_collect_fleet_snapshot_multi_device(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    z28_root = archive / "z28"
    (z28_root / "2026-06-30").mkdir(parents=True)
    (z28_root / "2026-06-30" / "orphan.wav").write_bytes(b"\x00" * 60_000)

    cfg = IdeaForgeConfig(
        archive=archive,
        devices=[DeviceBinding(name="z28", mount_glob="NO NAME", profile="z28")],
    )

    with (
        patch("ideaforge.fleet.check_daemon_health") as daemon,
        patch("ideaforge.fleet.check_menubar_health") as menubar,
        patch("ideaforge.fleet.find_recorder_mounts", return_value=[]),
        patch("ideaforge.fleet.load_status") as load_status,
    ):
        daemon.return_value = ServiceHealth("com.ideaforge.daemon", True, True, pid=42)
        menubar.return_value = ServiceHealth("com.ideaforge.menubar", True, False)
        reporter = StatusReporter(enabled=False)
        reporter.set_watching()
        load_status.return_value = reporter._status

        snapshot = collect_fleet_snapshot(cfg)

    assert snapshot["queue"]["pending_count"] >= 1
    assert len(snapshot["devices"]) == 1
    assert snapshot["devices"][0]["name"] == "z28"
    assert json.dumps(snapshot)
    html = render_fleet_html(snapshot)
    assert "IdeaForge Fleet" in html
    assert "z28" in html


def test_format_fleet_report_lists_device_queue(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    (archive / "2026-06-30").mkdir(parents=True)
    cfg = IdeaForgeConfig(archive=archive)

    with (
        patch("ideaforge.fleet.check_daemon_health") as daemon,
        patch("ideaforge.fleet.check_menubar_health") as menubar,
        patch("ideaforge.fleet.find_recorder_mounts", return_value=[]),
        patch("ideaforge.fleet.load_status") as load_status,
    ):
        daemon.return_value = ServiceHealth("com.ideaforge.daemon", True, False)
        menubar.return_value = ServiceHealth("com.ideaforge.menubar", False, False)
        reporter = StatusReporter(enabled=False)
        reporter.set_watching()
        load_status.return_value = reporter._status

        report = format_fleet_report(cfg)

    assert "fleet" in report.lower()
    assert "[default]" in report