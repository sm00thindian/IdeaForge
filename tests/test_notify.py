"""Tests for macOS completion notifications."""

from unittest.mock import patch

from ideaforge.notify import (
    ProcessResult,
    RecordingResult,
    format_completion_notification,
    notify_mac,
    notify_process_complete,
)


def test_format_single_recording_with_actions():
    result = ProcessResult(
        files_processed=1,
        recordings=[
            RecordingResult(
                stem="R2026-06-27-07-43-11",
                title="Sprint Planning",
                action_items=2,
                action_preview=["Alex: Send deck", "Jordan: Update roadmap"],
            )
        ],
    )
    title, subtitle, message = format_completion_notification(
        result,
        device_label="NO NAME",
    )
    assert title == "IdeaForge"
    assert subtitle == "Sprint Planning"
    assert "2 action items" in message
    assert "Alex: Send deck" in message


def test_format_all_skipped():
    result = ProcessResult(
        files_skipped=1,
        recordings=[RecordingResult(stem="rec", skipped=True)],
    )
    _, subtitle, message = format_completion_notification(
        result,
        device_label="Z29",
    )
    assert subtitle == "Already up to date"
    assert "Z29" in message


def test_notify_mac_on_darwin():
    with patch("ideaforge.notify.platform.system", return_value="Darwin"), patch(
        "ideaforge.notify.subprocess.run",
    ) as run:
        assert notify_mac(title="IdeaForge", subtitle="Done", message="3 action items")
    run.assert_called_once()


def test_notify_process_complete_prints_confirmation(capsys):
    result = ProcessResult(
        files_processed=1,
        recordings=[
            RecordingResult(stem="rec", title="Sync", action_items=1),
        ],
    )
    with patch("ideaforge.notify.notify_mac", return_value=True):
        notify_process_complete(result, device_label="NO NAME")
    assert "Notification sent" in capsys.readouterr().out