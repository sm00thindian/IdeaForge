"""Tests for daemon log rotation."""

from ideaforge.log_util import rotate_log_file


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