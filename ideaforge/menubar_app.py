"""macOS menu bar progress UI for IdeaForge."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path
from typing import IO, List, Optional

from ideaforge.branding import notification_icon_path
from ideaforge.config import IdeaForgeConfig
from ideaforge.health import DAEMON_LOG_PATH, open_daemon_log_tail
from ideaforge.archive_status import pending_failure_count
from ideaforge.status import (
    STATE_COMPLETE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PROCESSING,
    STATE_SETTLING,
    STATE_WATCHING,
    STEP_ACTIVE,
    STEP_DONE,
    STEP_PENDING,
    STEP_SKIPPED,
    PipelineStatus,
    default_status_path,
    format_elapsed,
    load_status,
    menu_bar_title,
)

LOCK_PATH = Path.home() / "Library" / "Application Support" / "IdeaForge" / "menubar.lock"


def _load_config() -> IdeaForgeConfig:
    cfg = IdeaForgeConfig()
    config_path = cfg.default_config_path()
    if config_path.is_file():
        cfg = IdeaForgeConfig.from_toml(config_path)
    return cfg


def _resolve_archive_path() -> Path:
    return _load_config().archive.expanduser()


def _menu_title_with_failures(status: PipelineStatus, failure_count: int) -> str:
    title = menu_bar_title(status)
    if failure_count <= 0:
        return title
    if status.state in (STATE_PROCESSING, STATE_SETTLING):
        return title
    if title in ("IdeaForge", "✓ IdeaForge"):
        return f"⚠{failure_count}"
    if title == "⚠ IdeaForge" and status.state == STATE_ERROR:
        return f"⚠{failure_count}"
    return title


def _open_path(path: Path) -> None:
    if path.exists():
        subprocess.run(["open", str(path)], check=False)


def _step_icon(status: str) -> str:
    return {
        STEP_DONE: "✓",
        STEP_ACTIVE: "●",
        STEP_PENDING: "○",
        STEP_SKIPPED: "–",
    }.get(status, "○")


def _pipeline_summary(status: PipelineStatus) -> str:
    if not status.steps:
        return "No active pipeline"
    parts = [f"{_step_icon(step.status)} {step.label}" for step in status.steps]
    return " · ".join(parts)


def _lock_holder_pid() -> Optional[int]:
    if not LOCK_PATH.is_file():
        return None
    try:
        return int(LOCK_PATH.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_singleton_lock() -> Optional[IO[str]]:
    """Return an open lock handle, or None if another instance is running."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        holder = _lock_holder_pid()
        if holder is not None and _pid_alive(holder):
            return None
        handle = LOCK_PATH.open("w", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


class IdeaForgeMenuBarApp:
    """Poll status.json and render a native menu bar item."""

    def __init__(self) -> None:
        import rumps  # type: ignore

        self._rumps = rumps
        icon = notification_icon_path()
        # Use icon + dynamic title on a single status item. Avoid launching twice.
        self.app = rumps.App(
            "IdeaForge",
            icon=str(icon) if icon.is_file() else None,
            quit_button="Quit IdeaForge Status",
        )
        self.app.title = ""
        self.status_item = rumps.MenuItem("Loading…", callback=None)
        self.detail_item = rumps.MenuItem("", callback=None)
        self.elapsed_item = rumps.MenuItem("", callback=None)
        self.pipeline_item = rumps.MenuItem("", callback=None)
        self.failures_item = rumps.MenuItem("", callback=None)
        self._archive_path = _resolve_archive_path()
        self._log_path = DAEMON_LOG_PATH

        self.app.menu = [
            self.status_item,
            self.detail_item,
            self.elapsed_item,
            self.pipeline_item,
            self.failures_item,
            None,
            rumps.MenuItem("Open Archive", callback=self.open_archive),
            rumps.MenuItem("Open Log", callback=self.open_log),
            rumps.MenuItem("Open Status File", callback=self.open_status_file),
        ]
        self._timer = rumps.Timer(self.refresh, 1)
        self._timer.start()
        self.refresh(None)

    def refresh(self, _) -> None:
        status = load_status()
        failure_count = pending_failure_count(_load_config())
        title = _menu_title_with_failures(status, failure_count)
        # Title appears beside the icon on the same menu bar item.
        self.app.title = "" if title == "IdeaForge" else title

        state_labels = {
            STATE_IDLE: "Idle",
            STATE_WATCHING: "Watching for recorder",
            STATE_SETTLING: "Waiting for mount to settle",
            STATE_PROCESSING: "Processing",
            STATE_COMPLETE: "Complete",
            STATE_ERROR: "Error",
        }
        headline = state_labels.get(status.state, status.state.title())
        if status.stage and status.state in (STATE_PROCESSING, STATE_SETTLING):
            headline = status.stage

        self.status_item.title = headline

        detail_parts: List[str] = []
        if status.recording:
            detail_parts.append(status.recording)
        if status.detail and status.detail not in detail_parts:
            detail_parts.append(status.detail)
        if status.progress is not None and status.state == STATE_PROCESSING:
            detail_parts.append(f"{int(status.progress * 100)}%")
        self.detail_item.title = " · ".join(detail_parts) if detail_parts else "—"

        elapsed = format_elapsed(status)
        session_hint = ""
        if status.sessions_total > 1 and status.session:
            session_hint = f" · session {status.session}/{status.sessions_total}"
        self.elapsed_item.title = f"Elapsed {elapsed}{session_hint}"
        self.pipeline_item.title = _pipeline_summary(status)

        if failure_count:
            noun = "session" if failure_count == 1 else "sessions"
            self.failures_item.title = (
                f"⚠ {failure_count} failed {noun} — retry from archive"
            )
        else:
            self.failures_item.title = "No pending failures"

    def open_archive(self, _) -> None:
        _open_path(self._archive_path)

    def open_log(self, _) -> None:
        if not open_daemon_log_tail(self._log_path):
            _open_path(self._log_path)

    def open_status_file(self, _) -> None:
        _open_path(default_status_path())

    def run(self) -> None:
        self.app.run()


def main(argv: Optional[List[str]] = None) -> int:
    try:
        import rumps  # type: ignore  # noqa: F401
    except ImportError:
        print(
            "rumps is required for the menu bar app. "
            "Install with: pip install 'ideaforge[menubar]'",
            flush=True,
        )
        return 1

    lock = acquire_singleton_lock()
    if lock is None:
        return 0

    try:
        IdeaForgeMenuBarApp().run()
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
        if LOCK_PATH.is_file():
            LOCK_PATH.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())