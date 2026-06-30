"""Tests for daemon config validation at startup."""

import argparse
from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.daemon import run_daemon


def test_daemon_exits_on_invalid_config(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('archive = "~/IdeaForge"\n[llm]\nbackend = "not-a-backend"\n', encoding="utf-8")
    cfg = IdeaForgeConfig.from_toml(config)
    args = argparse.Namespace(force=False)

    with patch("ideaforge.daemon.RecorderWatcher"):
        code = run_daemon(cfg, args, config_path=config)

    assert code == 1