"""Tests for menu bar Open Log behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ideaforge.menubar_app import IdeaForgeMenuBarApp


def test_open_log_tails_in_terminal(tmp_path: Path):
    app = object.__new__(IdeaForgeMenuBarApp)
    app._log_path = tmp_path / "daemon.log"

    with (
        patch("ideaforge.menubar_app.open_daemon_log_tail", return_value=True) as tail,
        patch("ideaforge.menubar_app._open_path") as open_path,
    ):
        app.open_log(None)

    tail.assert_called_once_with(app._log_path)
    open_path.assert_not_called()


def test_open_log_falls_back_when_terminal_unavailable(tmp_path: Path):
    app = object.__new__(IdeaForgeMenuBarApp)
    app._log_path = tmp_path / "daemon.log"

    with (
        patch("ideaforge.menubar_app.open_daemon_log_tail", return_value=False),
        patch("ideaforge.menubar_app._open_path") as open_path,
    ):
        app.open_log(None)

    open_path.assert_called_once_with(app._log_path)