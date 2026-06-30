"""Tests for [[devices]] config validation."""

from pathlib import Path

import pytest

from ideaforge.config import IdeaForgeConfig
from ideaforge.config_validate import ConfigValidationError, validate_config_file


def test_validate_config_accepts_devices_section(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
archive = "~/IdeaForge"

[[devices]]
name = "office-z28"
mount_glob = "NO NAME"
profile = "z28"
""".strip(),
        encoding="utf-8",
    )
    cfg = validate_config_file(config, check_paths=False)
    assert len(cfg.devices) == 1
    assert cfg.devices[0].name == "office-z28"


def test_validate_config_accepts_device_chunk_mode(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
archive = "~/IdeaForge"

[[devices]]
name = "field"
mount_glob = "REC"
profile = "generic_wav"
chunk_mode = "fixed_window"
""".strip(),
        encoding="utf-8",
    )
    cfg = validate_config_file(config, check_paths=False)
    assert cfg.devices[0].chunk_mode == "fixed_window"


def test_validate_config_rejects_unknown_profile(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[[devices]]
name = "x"
mount_glob = "*"
profile = "unknown"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError, match="profile"):
        validate_config_file(config, check_paths=False)