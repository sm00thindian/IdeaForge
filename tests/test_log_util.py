"""Tests for daemon log rotation."""

import os
from datetime import date, datetime

from ideaforge.log_util import (
    is_daily_rotation_due,
    list_log_files,
    load_last_rotated_date,
    rotate_all_logs,
    rotate_log_file,
    save_last_rotated_date,
)


def test_rotate_log_file_skips_small_files(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_text("small\n", encoding="utf-8")
    assert rotate_log_file(log, max_bytes=1000) is False
    assert log.read_text(encoding="utf-8") == "small\n"


def test_rotate_log_file_rotates_when_over_limit(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_bytes(b"x" * 200)
    assert rotate_log_file(log, max_bytes=100, backups=2) is True
    assert log.read_text(encoding="utf-8") == ""
    backup = tmp_path / "daemon.log.1"
    assert backup.read_bytes() == b"x" * 200


def test_rotate_log_file_force_rotates_small_files(tmp_path):
    log = tmp_path / "reprocess.log"
    log.write_text("tiny\n", encoding="utf-8")
    assert rotate_log_file(log, force=True, backups=2) is True
    assert log.read_text(encoding="utf-8") == ""
    assert (tmp_path / "reprocess.log.1").read_text(encoding="utf-8") == "tiny\n"


def test_list_log_files_ignores_numbered_backups(tmp_path):
    (tmp_path / "daemon.log").write_text("a", encoding="utf-8")
    (tmp_path / "daemon.log.1").write_text("b", encoding="utf-8")
    (tmp_path / "menubar.log").write_text("c", encoding="utf-8")
    names = [path.name for path in list_log_files(tmp_path)]
    assert names == ["daemon.log", "menubar.log"]


def test_rotate_all_logs_rotates_every_active_log(tmp_path):
    (tmp_path / "daemon.log").write_text("one\n", encoding="utf-8")
    (tmp_path / "daemon.err.log").write_text("two\n", encoding="utf-8")
    (tmp_path / "reprocess.log").write_text("three\n", encoding="utf-8")
    rotated = rotate_all_logs(tmp_path, force=True, backups=2)
    assert {path.name for path in rotated} == {
        "daemon.log",
        "daemon.err.log",
        "reprocess.log",
    }


def test_is_daily_rotation_due_before_scheduled_time():
    now = datetime(2026, 7, 2, 1, 30, 0)
    assert is_daily_rotation_due(now, hour=2, minute=0, last_rotated=None) is False


def test_is_daily_rotation_due_after_scheduled_time():
    now = datetime(2026, 7, 2, 2, 5, 0)
    assert is_daily_rotation_due(now, hour=2, minute=0, last_rotated=None) is True


def test_is_daily_rotation_due_skips_after_rotation_today():
    today = date(2026, 7, 2)
    now = datetime(2026, 7, 2, 3, 0, 0)
    assert is_daily_rotation_due(now, hour=2, minute=0, last_rotated=today) is False


def test_is_daily_rotation_due_catches_up_after_missed_window():
    now = datetime(2026, 7, 2, 8, 0, 0)
    assert is_daily_rotation_due(now, hour=2, minute=0, last_rotated=date(2026, 7, 1)) is True


def test_rotate_log_file_preserves_inode_for_open_writers(tmp_path):
    log = tmp_path / "daemon.log"
    log.write_text("before\n", encoding="utf-8")
    inode_before = log.stat().st_ino
    fd = os.open(log, os.O_WRONLY | os.O_APPEND)
    try:
        assert rotate_log_file(log, force=True, backups=2) is True
        os.write(fd, b"after\n")
    finally:
        os.close(fd)
    assert log.stat().st_ino == inode_before
    assert log.read_text(encoding="utf-8") == "after\n"
    assert (tmp_path / "daemon.log.1").read_text(encoding="utf-8") == "before\n"


def test_rotate_date_state_round_trip(tmp_path, monkeypatch):
    state = tmp_path / "log-rotate-date"
    monkeypatch.setattr("ideaforge.log_util.ROTATE_STATE_PATH", state)
    assert load_last_rotated_date() is None
    save_last_rotated_date(date(2026, 7, 2))
    assert load_last_rotated_date() == date(2026, 7, 2)