"""Tests for config validation."""

from pathlib import Path

import pytest

from ideaforge.config import IdeaForgeConfig
from ideaforge.config_validate import (
    ConfigValidationError,
    collect_runtime_warnings,
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


def test_validate_config_rejects_negative_merged_wav_retain_days():
    cfg = IdeaForgeConfig(daemon_merged_wav_retain_days=-1)
    with pytest.raises(ConfigValidationError) as exc:
        validate_config(cfg)
    assert "merged_wav_retain_days" in str(exc.value)


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


def test_collect_runtime_warnings_empty_when_tools_present(tmp_path: Path):
    cfg = IdeaForgeConfig(
        archive=tmp_path,
        merge_to_mp3=True,
        normalize_audio=True,
        diarize=False,
        llm_backend="ollama",
    )
    from unittest.mock import patch

    with (
        patch("ideaforge.config_validate._tool_on_path", return_value="/usr/bin/ffmpeg"),
        patch("ideaforge.config.has_xai_api_key", return_value=False),
    ):
        warnings = collect_runtime_warnings(cfg)
    # ollama backend should not warn about missing XAI
    assert not any("merge_to_mp3" in w for w in warnings)
    assert not any("XAI_API_KEY" in w for w in warnings)