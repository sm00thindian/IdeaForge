"""Tests for menubar pending failure badge."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.ingest import load_processed_log, record_session_failure, save_processed_log
from ideaforge.menubar_app import (
    IdeaForgeMenuBarApp,
    _menu_title_with_failures,
    _pending_failure_count,
)
from ideaforge.status import STATE_IDLE, STATE_PROCESSING, PipelineStatus, StatusReporter


def test_pending_failure_count(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    log = load_processed_log(archive)
    record_session_failure(
        log,
        session_stem="R2026-06-30-08-00-00",
        archive_folder=archive / "2026-06-30",
        archive_files=[],
        chunk_hashes=[],
        error="x",
        pipeline="test",
    )
    save_processed_log(archive, log)
    assert _pending_failure_count(archive) == 1


def test_menu_title_shows_failure_badge_when_idle():
    status = PipelineStatus(state=STATE_IDLE)
    assert _menu_title_with_failures(status, 2) == "⚠2"


def test_menu_title_keeps_processing_title():
    status = PipelineStatus(state=STATE_PROCESSING, stage="Transcribing")
    reporter = StatusReporter(enabled=False)
    reporter._status = status
    title = _menu_title_with_failures(status, 3)
    assert "Transcribing" in title or title.startswith("⟳")


def test_menubar_refresh_sets_failures_menu_item(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    log = load_processed_log(archive)
    record_session_failure(
        log,
        session_stem="R2026-06-30-08-00-00",
        archive_folder=archive / "2026-06-30",
        archive_files=[],
        chunk_hashes=[],
        error="x",
        pipeline="test",
    )
    save_processed_log(archive, log)

    app = object.__new__(IdeaForgeMenuBarApp)
    app.failures_item = type("Item", (), {"title": ""})()
    app._archive_path = archive
    app.status_item = type("Item", (), {"title": ""})()
    app.detail_item = type("Item", (), {"title": ""})()
    app.elapsed_item = type("Item", (), {"title": ""})()
    app.pipeline_item = type("Item", (), {"title": ""})()
    app.app = type("App", (), {"title": ""})()

    with patch("ideaforge.menubar_app.load_status", return_value=PipelineStatus(state=STATE_IDLE)):
        app.refresh(None)

    assert "1 failed session" in app.failures_item.title
    assert app.app.title == "⚠1"