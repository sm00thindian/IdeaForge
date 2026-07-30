"""Tests for menubar pending failure badge."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ideaforge.archive_status import pending_failure_count
from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import load_processed_log, record_session_failure, save_processed_log
from ideaforge.health import ServiceHealth
from ideaforge.menubar_app import (
    IdeaForgeMenuBarApp,
    _menu_title_with_failures,
)
from ideaforge.status import (
    STATE_IDLE,
    STATE_PROCESSING,
    LastNote,
    Stage,
    PipelineStatus,
    StatusReporter,
    load_last_notes,
    save_last_notes,
)


class _MenuItemStub:
    def __init__(self, title: str = "", callback=None, **_kwargs) -> None:
        self.title = title
        self.callback = callback
        self.children: list = []
        self._menu = None
        self._menuitem = type("NS", (), {"setEnabled_": lambda self, v: None, "setSubmenu_": lambda self, v: None})()

    def set_callback(self, cb) -> None:
        self.callback = cb

    def clear(self) -> None:
        self.children.clear()

    def add(self, item) -> None:
        self._menu = True
        self.children.append(item)


def _stub_menubar_app(archive: Path) -> IdeaForgeMenuBarApp:
    app = object.__new__(IdeaForgeMenuBarApp)
    app.failures_item = _MenuItemStub()
    app.retry_failed_item = _MenuItemStub("Retry Failed Sessions")
    app.daemon_item = _MenuItemStub()
    app.last_notes_item = _MenuItemStub("No recent notes")
    app.start_daemon_item = _MenuItemStub("Start Daemon")
    app.stop_daemon_item = _MenuItemStub("Stop Daemon")
    app.restart_daemon_item = _MenuItemStub("Restart Daemon")
    app.restart_menubar_item = _MenuItemStub("Restart Menubar")
    app._archive_path = archive
    app.status_item = _MenuItemStub()
    app.detail_item = _MenuItemStub()
    app.elapsed_item = _MenuItemStub()
    app.pipeline_item = _MenuItemStub()
    app.app = type("App", (), {"title": ""})()
    app._last_notes_signature = None
    app._seeded_last_notes = True  # tests control notes via mocks
    app._rumps = MagicMock()
    app._rumps.MenuItem = _MenuItemStub
    return app


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
    cfg = IdeaForgeConfig(archive=archive)
    assert pending_failure_count(cfg) == 1


def test_menu_title_shows_failure_badge_when_idle():
    status = PipelineStatus(state=STATE_IDLE)
    assert _menu_title_with_failures(status, 2) == "⚠2"


def test_menu_title_keeps_processing_title():
    status = PipelineStatus(state=STATE_PROCESSING, stage=Stage.TRANSCRIBING)
    reporter = StatusReporter(enabled=False)
    reporter._status = status
    title = _menu_title_with_failures(status, 3)
    assert Stage.TRANSCRIBING in title or title.startswith("⟳")


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

    app = _stub_menubar_app(archive)

    cfg = IdeaForgeConfig(archive=archive)
    daemon = ServiceHealth("com.ideaforge.daemon", installed=True, running=True, pid=42)
    menubar = ServiceHealth("com.ideaforge.menubar", installed=True, running=True, pid=43)
    with (
        patch("ideaforge.menubar_app.load_status", return_value=PipelineStatus(state=STATE_IDLE)),
        patch("ideaforge.menubar_app._load_config", return_value=cfg),
        patch("ideaforge.menubar_app.check_daemon_health", return_value=daemon),
        patch("ideaforge.menubar_app.check_menubar_health", return_value=menubar),
        patch("ideaforge.menubar_app.load_last_notes", return_value=[]),
    ):
        app.refresh(None)

    assert "1 failed session" in app.failures_item.title
    assert app.app.title == "⚠1"
    assert app.last_notes_item.title == "No recent notes"
    assert app.retry_failed_item.callback is not None


def test_menubar_refresh_shows_daemon_status(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()

    app = _stub_menubar_app(archive)

    cfg = IdeaForgeConfig(archive=archive)
    daemon = ServiceHealth("com.ideaforge.daemon", installed=True, running=False)
    menubar = ServiceHealth("com.ideaforge.menubar", installed=True, running=True, pid=1)
    with (
        patch("ideaforge.menubar_app.load_status", return_value=PipelineStatus(state=STATE_IDLE)),
        patch("ideaforge.menubar_app._load_config", return_value=cfg),
        patch("ideaforge.menubar_app.check_daemon_health", return_value=daemon),
        patch("ideaforge.menubar_app.check_menubar_health", return_value=menubar),
        patch("ideaforge.menubar_app.load_last_notes", return_value=[]),
    ):
        app.refresh(None)

    assert app.daemon_item.title == "Daemon: stopped (LaunchAgent installed)"


def test_menubar_shows_single_last_note_link(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    md = tmp_path / "20260630 - Standup.md"
    md.write_text("# notes", encoding="utf-8")
    store = tmp_path / "last_notes.json"
    save_last_notes(
        [LastNote(path=str(md), title="Standup", stem="R1")],
        path=store,
    )

    app = _stub_menubar_app(archive)
    cfg = IdeaForgeConfig(archive=archive)
    daemon = ServiceHealth("com.ideaforge.daemon", installed=True, running=True, pid=1)
    menubar = ServiceHealth("com.ideaforge.menubar", installed=True, running=True, pid=1)
    with (
        patch("ideaforge.menubar_app.load_status", return_value=PipelineStatus(state=STATE_IDLE)),
        patch("ideaforge.menubar_app._load_config", return_value=cfg),
        patch("ideaforge.menubar_app.check_daemon_health", return_value=daemon),
        patch("ideaforge.menubar_app.check_menubar_health", return_value=menubar),
        patch(
            "ideaforge.menubar_app.load_last_notes",
            return_value=load_last_notes(store),
        ),
    ):
        app.refresh(None)

    assert app.last_notes_item.title == "Open Notes: Standup"
    assert app.last_notes_item.callback is not None


def test_menubar_shows_multiple_last_notes_submenu(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    m1 = tmp_path / "a.md"
    m2 = tmp_path / "b.md"
    m1.write_text("a", encoding="utf-8")
    m2.write_text("b", encoding="utf-8")
    notes = [
        LastNote(path=str(m1), title="Meeting A"),
        LastNote(path=str(m2), title="Blue skies", output_intent="song_idea"),
    ]

    app = _stub_menubar_app(archive)
    cfg = IdeaForgeConfig(archive=archive)
    daemon = ServiceHealth("com.ideaforge.daemon", installed=True, running=True, pid=1)
    menubar = ServiceHealth("com.ideaforge.menubar", installed=True, running=True, pid=1)
    with (
        patch("ideaforge.menubar_app.load_status", return_value=PipelineStatus(state=STATE_IDLE)),
        patch("ideaforge.menubar_app._load_config", return_value=cfg),
        patch("ideaforge.menubar_app.check_daemon_health", return_value=daemon),
        patch("ideaforge.menubar_app.check_menubar_health", return_value=menubar),
        patch("ideaforge.menubar_app.load_last_notes", return_value=notes),
    ):
        app.refresh(None)

    assert app.last_notes_item.title == "Open Last Notes (2)"
    assert app.last_notes_item.callback is not None  # parent must stay clickable
    assert len(app.last_notes_item.children) == 2
    assert app.last_notes_item.children[1].title == "2. 🎵 Blue skies"