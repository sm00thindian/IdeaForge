"""Tests for menu bar singleton lock."""

import os
from unittest.mock import patch

from ideaforge.menubar_app import LOCK_PATH, acquire_singleton_lock


def test_acquire_singleton_lock_prevents_second_instance(tmp_path, monkeypatch):
    monkeypatch.setattr("ideaforge.menubar_app.LOCK_PATH", tmp_path / "menubar.lock")

    first = acquire_singleton_lock()
    assert first is not None
    second = acquire_singleton_lock()
    assert second is None

    fcntl = __import__("fcntl")
    fcntl.flock(first.fileno(), fcntl.LOCK_UN)
    first.close()


def test_acquire_singleton_lock_reclaims_stale_lock(tmp_path, monkeypatch):
    lock_path = tmp_path / "menubar.lock"
    monkeypatch.setattr("ideaforge.menubar_app.LOCK_PATH", lock_path)
    lock_path.write_text("999999999", encoding="utf-8")

    handle = acquire_singleton_lock()
    assert handle is not None
    assert lock_path.read_text(encoding="utf-8") == str(os.getpid())

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()