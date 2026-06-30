"""Tests for config validation."""

from pathlib import Path

import pytest

from ideaforge.config import IdeaForgeConfig
from ideaforge.config_validate import (
    ConfigValidationError,
    find_unknown_keys,
    validate_config,
    validate_config_file,
)


def test_find_unknown_keys_reports_typos():
    data = {
        "archive": "~/IdeaForge",
        "llm": {"backend": "auto", "grok_modle": "grok-4.3"},
        "daemon": {"poll_interval_seconds": 5, "notifyy": True},
        "typo_section": {},
    }
    issues = find_unknown_keys(data)
    assert any("typo_section" in item for item in issues)
    assert any("grok_modle" in item for item in issues)
    assert any("notifyy" in item for item in issues)


def test_validate_config_rejects_invalid_backend():
    cfg = IdeaForgeConfig(llm_backend="chatgpt")
    with pytest.raises(ConfigValidationError) as exc:
        validate_config(cfg)
    assert "llm.backend" in str(exc.value)


def test_validate_config_file_ok(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
archive = "~/IdeaForge"

[llm]
backend = "auto"

[daemon]
poll_interval_seconds = 5
""".strip(),
        encoding="utf-8",
    )
    cfg = validate_config_file(config, check_paths=False)
    assert cfg.llm_backend == "auto"


def test_validate_config_file_unknown_key(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
archive = "~/IdeaForge"
unknown_flag = true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError) as exc:
        validate_config_file(config, check_paths=False)
    assert "unknown top-level" in str(exc.value)