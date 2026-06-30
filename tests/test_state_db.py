"""Tests for versioned processed log state."""

import json
from pathlib import Path

import pytest

from ideaforge.state_db import (
    PROCESSED_LOG_SCHEMA_VERSION,
    load_processed_log,
    migrate_processed_log,
    save_processed_log,
)


def test_migrate_legacy_log_adds_schema_version():
    raw = {"hashes": ["abc"], "files": {}, "failures": {}}
    migrated = migrate_processed_log(raw)
    assert migrated["schema_version"] == PROCESSED_LOG_SCHEMA_VERSION
    assert migrated["hashes"] == ["abc"]


def test_migrate_legacy_failure_adds_failed_at():
    raw = {
        "failures": {
            "R2026-06-30-08-00-00": {
                "session_stem": "R2026-06-30-08-00-00",
                "error": "boom",
            }
        }
    }
    migrated = migrate_processed_log(raw)
    entry = migrated["failures"]["R2026-06-30-08-00-00"]
    assert "failed_at" in entry


def test_save_writes_schema_version(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    log = load_processed_log(archive)
    save_processed_log(archive, log)
    data = json.loads((archive / ".processed_log.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == PROCESSED_LOG_SCHEMA_VERSION


def test_unsupported_schema_version_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        migrate_processed_log({"schema_version": 99, "hashes": [], "files": {}, "failures": {}})