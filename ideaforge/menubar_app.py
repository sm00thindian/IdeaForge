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
from ideaforge.health import (
    DAEMON_LOG_PATH,
    ServiceHealth,
    check_daemon_health,
    check_menubar_health,
    open_daemon_log_tail,
    restart_daemon_service,
    restart_menubar_service,
    start_daemon_service,
    start_retry_failed_job,
    stop_daemon_service,
)
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
    LastNote,
    PipelineStatus,
    default_status_path,
    format_elapsed,
    format_eta,
    load_last_notes,
    load_status,
    menu_bar_title,
    resolve_display_status,
    seed_last_notes_from_archive,
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
        self.retry_failed_item = rumps.MenuItem(
            "Retry Failed Sessions",
            callback=None,
        )
        self.daemon_item = rumps.MenuItem("", callback=None)
        self.last_notes_item = rumps.MenuItem("No recent notes", callback=None)
        self.start_daemon_item = rumps.MenuItem("Start Daemon", callback=self.start_daemon)
        self.stop_daemon_item = rumps.MenuItem("Stop Daemon", callback=self.stop_daemon)
        self.restart_daemon_item = rumps.MenuItem("Restart Daemon", callback=self.restart_daemon)
        self.restart_menubar_item = rumps.MenuItem(
            "Restart Menubar",
            callback=self.restart_menubar,
        )
        self._archive_path = _resolve_archive_path()
        self._log_path = DAEMON_LOG_PATH
        self._last_notes_signature: Optional[tuple] = None
        self._seeded_last_notes = False

        self.app.menu = [
            self.status_item,
            self.detail_item,
            self.elapsed_item,
            self.pipeline_item,
            self.failures_item,
            self.retry_failed_item,
            self.daemon_item,
            self.last_notes_item,
            None,
            self.start_daemon_item,
            self.stop_daemon_item,
            self.restart_daemon_item,
            self.restart_menubar_item,
            None,
            rumps.MenuItem("Open Archive", callback=self.open_archive),
            rumps.MenuItem("Open Log", callback=self.open_log),
            rumps.MenuItem("Open Status File", callback=self.open_status_file),
        ]
        self._timer = rumps.Timer(self.refresh, 1)
        self._timer.start()
        self.refresh(None)

    def refresh(self, _) -> None:
        status = resolve_display_status(load_status())
        daemon = check_daemon_health()
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
        if status.output_intent == "song_idea" and status.state == STATE_PROCESSING:
            if headline in ("Meeting notes", "Summarizing"):
                headline = "Song idea"

        self.status_item.title = headline

        detail_parts: List[str] = []
        if status.recording:
            detail_parts.append(status.recording)
        if status.detail and status.detail not in detail_parts:
            detail_parts.append(status.detail)
        if status.progress is not None and status.state == STATE_PROCESSING:
            detail_parts.append(f"{int(status.progress * 100)}%")
        eta_label = format_eta(status)
        if eta_label and status.state == STATE_PROCESSING:
            detail_parts.append(eta_label)
        self.detail_item.title = " · ".join(detail_parts) if detail_parts else "—"

        elapsed = format_elapsed(status)
        session_hint = ""
        if status.sessions_total > 1 and status.session:
            session_hint = f" · session {status.session}/{status.sessions_total}"
        eta_suffix = f" · ETA {eta_label}" if eta_label and status.state == STATE_PROCESSING else ""
        self.elapsed_item.title = f"Elapsed {elapsed}{session_hint}{eta_suffix}"
        self.pipeline_item.title = _pipeline_summary(status)

        if failure_count:
            noun = "session" if failure_count == 1 else "sessions"
            self.failures_item.title = f"⚠ {failure_count} failed {noun}"
            self.retry_failed_item.title = f"Retry {failure_count} Failed Session(s)"
            self.retry_failed_item.set_callback(self.retry_failed)
        else:
            self.failures_item.title = "No pending failures"
            self.retry_failed_item.title = "Retry Failed Sessions"
            self.retry_failed_item.set_callback(None)

        self.daemon_item.title = f"Daemon: {daemon.status_line}"
        self._update_daemon_controls(daemon)
        self._update_last_notes_menu()

    def _update_last_notes_menu(self) -> None:
        notes = load_last_notes()
        if not notes and not self._seeded_last_notes:
            self._seeded_last_notes = True
            cfg = _load_config()
            notes = seed_last_notes_from_archive(cfg.archive.expanduser())
        signature = tuple((n.path, n.title, n.output_intent) for n in notes)
        if signature == self._last_notes_signature:
            return
        self._last_notes_signature = signature
        self._rebuild_last_notes_menu(notes)

    def _clear_last_notes_submenu(self) -> None:
        """Remove prior submenu children without greying out the parent item."""
        try:
            # rumps clear() requires an existing NSMenu; ignore if never nested.
            if getattr(self.last_notes_item, "_menu", None) is not None:
                self.last_notes_item.clear()
        except Exception:
            pass
        # Detach empty submenu so a single-note click target is not a submenu header.
        try:
            self.last_notes_item._menu = None
            self.last_notes_item._menuitem.setSubmenu_(None)
        except Exception:
            pass

    def _rebuild_last_notes_menu(self, notes: List[LastNote]) -> None:
        rumps = self._rumps
        self._clear_last_notes_submenu()

        if not notes:
            self.last_notes_item.title = "No recent notes"
            self.last_notes_item.set_callback(None)
            return

        def _add_sidecar_items(parent, note: LastNote) -> None:
            if note.suno_path and Path(note.suno_path).is_file():
                suno = note.suno_path
                parent.add(
                    rumps.MenuItem(
                        "Open Suno sidecar",
                        callback=lambda _s=None, p=suno: _open_path(Path(p)),
                    )
                )
            if note.udio_path and Path(note.udio_path).is_file():
                udio = note.udio_path
                parent.add(
                    rumps.MenuItem(
                        "Open Udio sidecar",
                        callback=lambda _s=None, p=udio: _open_path(Path(p)),
                    )
                )

        if len(notes) == 1:
            note = notes[0]
            self.last_notes_item.title = f"Open Notes: {note.menu_label}"
            path = note.path
            self.last_notes_item.set_callback(
                lambda _sender=None, note_path=path: _open_path(Path(note_path))
            )
            _add_sidecar_items(self.last_notes_item, note)
            try:
                self.last_notes_item._menuitem.setEnabled_(True)
            except Exception:
                pass
            return

        # Multiple notes: keep parent ENABLED (rumps greys out callback=None).
        # Click parent → open first note; hover submenu → pick a specific file.
        self.last_notes_item.title = f"Open Last Notes ({len(notes)})"
        first_path = notes[0].path
        self.last_notes_item.set_callback(
            lambda _sender=None, note_path=first_path: _open_path(Path(note_path))
        )
        for index, note in enumerate(notes, start=1):
            path = note.path
            label = f"{index}. {note.menu_label}"
            has_sidecars = (
                (note.suno_path and Path(note.suno_path).is_file())
                or (note.udio_path and Path(note.udio_path).is_file())
            )
            if has_sidecars:
                group = rumps.MenuItem(label)
                group.add(
                    rumps.MenuItem(
                        "Open notes",
                        callback=lambda _s=None, p=path: _open_path(Path(p)),
                    )
                )
                _add_sidecar_items(group, note)
                self.last_notes_item.add(group)
            else:
                item = rumps.MenuItem(
                    label,
                    callback=lambda _sender=None, note_path=path: _open_path(
                        Path(note_path)
                    ),
                )
                self.last_notes_item.add(item)
        try:
            self.last_notes_item._menuitem.setEnabled_(True)
        except Exception:
            pass

    def _update_daemon_controls(self, daemon: ServiceHealth) -> None:
        can_manage = daemon.installed
        self.start_daemon_item.set_callback(
            self.start_daemon if can_manage and not daemon.running else None
        )
        self.stop_daemon_item.set_callback(
            self.stop_daemon if can_manage and daemon.running else None
        )
        self.restart_daemon_item.set_callback(
            self.restart_daemon if can_manage else None
        )
        menubar = check_menubar_health()
        self.restart_menubar_item.set_callback(
            self.restart_menubar if menubar.installed else None
        )

    def _notify_service_action(self, ok: bool, message: str, *, kind: str = "service") -> None:
        title = "IdeaForge" if ok else f"IdeaForge — {kind} error"
        self._rumps.notification(title, None, message, sound=False)

    def start_daemon(self, _) -> None:
        ok, message = start_daemon_service()
        self._notify_service_action(ok, message, kind="daemon")
        self.refresh(None)

    def stop_daemon(self, _) -> None:
        ok, message = stop_daemon_service()
        self._notify_service_action(ok, message, kind="daemon")
        self.refresh(None)

    def restart_daemon(self, _) -> None:
        ok, message = restart_daemon_service()
        self._notify_service_action(ok, message, kind="daemon")
        self.refresh(None)

    def restart_menubar(self, _) -> None:
        ok, message = restart_menubar_service()
        self._notify_service_action(ok, message, kind="menubar")
        # Process may exit soon after kickstart; no need to refresh.

    def retry_failed(self, _) -> None:
        ok, message = start_retry_failed_job(_load_config())
        self._notify_service_action(ok, message, kind="retry")
        self.refresh(None)

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