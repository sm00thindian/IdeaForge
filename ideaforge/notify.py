"""macOS user notifications for IdeaForge."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence


@dataclass
class RecordingResult:
    stem: str
    title: Optional[str] = None
    action_items: int = 0
    action_preview: List[str] = field(default_factory=list)
    output_intent: Optional[str] = None
    summary_md: Optional[str] = None
    skipped: bool = False
    failed: bool = False
    empty: bool = False


@dataclass
class ProcessResult:
    files_processed: int = 0
    files_skipped: int = 0
    recordings: List[RecordingResult] = field(default_factory=list)


def format_completion_notification(
    result: ProcessResult,
    *,
    device_label: str,
) -> tuple[str, str, str]:
    """Return (title, subtitle, message) for a completion notification."""
    title = "IdeaForge"

    if result.files_processed == 0 and result.files_skipped > 0:
        subtitle = "Already up to date"
        message = (
            f"{result.files_skipped} recording(s) on {device_label} — "
            "outputs already exist"
        )
        return title, subtitle, message

    if result.files_processed == 1 and result.recordings:
        rec = next((r for r in result.recordings if not r.skipped), result.recordings[0])
        if rec.empty:
            return title, rec.stem, "Silent recording — audio discarded"
        subtitle = rec.title or rec.stem
        parts: List[str] = []
        if rec.action_items:
            parts.append(
                f"{rec.action_items} action item{'s' if rec.action_items != 1 else ''}"
            )
        if rec.action_preview:
            parts.append(" · ".join(rec.action_preview[:2]))
        if rec.output_intent == "song_idea":
            default_message = "Suno and Udio prompts saved"
        else:
            default_message = "Meeting notes saved"
        message = " · ".join(parts) if parts else default_message
        return title, subtitle, message

    subtitle = f"{result.files_processed} recording(s) processed"
    total_actions = sum(r.action_items for r in result.recordings if not r.skipped)
    if total_actions:
        message = f"{total_actions} total action items from {device_label}"
    else:
        message = f"Pipeline complete for {device_label}"
    return title, subtitle, message


def _terminal_notifier_paths() -> Sequence[str]:
    candidates = [
        shutil.which("terminal-notifier"),
        "/opt/homebrew/bin/terminal-notifier",
        "/usr/local/bin/terminal-notifier",
    ]
    return [path for path in candidates if path]


def _notification_icon_path() -> Optional[Path]:
    try:
        from ideaforge.branding import notification_icon_path

        icon = notification_icon_path()
    except (ImportError, FileNotFoundError, ModuleNotFoundError):
        return None
    return icon if icon.is_file() else None


def notify_mac(
    *,
    title: str,
    message: str,
    subtitle: Optional[str] = None,
    sound: bool = True,
    open_path: Optional[str] = None,
) -> bool:
    """Show a macOS notification. Returns True if dispatched.

    When ``open_path`` is set and terminal-notifier is available, clicking the
    notification opens that file (or folder). AppleScript fallback cannot open
    on click.
    """
    if platform.system() != "Darwin":
        return False

    icon = _notification_icon_path()
    for notifier in _terminal_notifier_paths():
        cmd = [
            notifier,
            "-title",
            title,
            "-message",
            message,
        ]
        if subtitle:
            cmd.extend(["-subtitle", subtitle])
        if icon is not None:
            cmd.extend(["-appIcon", str(icon)])
        if sound:
            cmd.extend(["-sound", "Glass"])
        if open_path:
            # file:// or bare path — terminal-notifier accepts -open for click action
            open_target = open_path
            if not open_target.startswith("file:") and Path(open_target).exists():
                open_target = Path(open_target).resolve().as_uri()
            cmd.extend(["-open", open_target])
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    lines = [
        f'display notification "{_escape_applescript(message)}" '
        f'with title "{_escape_applescript(title)}"',
    ]
    if subtitle:
        lines[0] += f' subtitle "{_escape_applescript(subtitle)}"'
    if sound:
        lines[0] += ' sound name "Glass"'

    script = "\n".join(lines)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def format_failure_notification(
    session_stem: str,
    error: str,
) -> tuple[str, str, str]:
    """Return (title, subtitle, message) for a session failure notification."""
    title = "IdeaForge"
    subtitle = "Session failed"
    message = session_stem
    detail = error.strip()
    if detail:
        message = f"{session_stem} — {detail[:240]}"
    return title, subtitle, message


def notify_session_failure(session_stem: str, error: str) -> bool:
    """Show a macOS notification for a failed pipeline session."""
    title, subtitle, message = format_failure_notification(session_stem, error)
    if notify_mac(title=title, message=message, subtitle=subtitle):
        print(f"    🔔 Failure notification sent: {session_stem}")
        return True
    return False


def first_openable_notes_path(result: ProcessResult) -> Optional[str]:
    """First existing markdown path from a completed process result."""
    for rec in result.recordings:
        if rec.skipped or rec.failed or rec.empty:
            continue
        if not rec.summary_md:
            continue
        path = Path(rec.summary_md)
        if path.is_file():
            return str(path.resolve())
    return None


def notify_process_complete(
    result: ProcessResult,
    *,
    device_label: str,
) -> None:
    title, subtitle, message = format_completion_notification(
        result,
        device_label=device_label,
    )
    open_path = first_openable_notes_path(result)
    if notify_mac(
        title=title,
        message=message,
        subtitle=subtitle,
        open_path=open_path,
    ):
        hint = f" (click to open notes)" if open_path else ""
        print(f"    🔔 Notification sent: {subtitle}{hint}")


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')