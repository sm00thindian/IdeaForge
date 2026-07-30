"""Tests for ideaforge doctor and runtime warnings."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.config_validate import collect_runtime_warnings
from ideaforge.doctor import format_doctor_report, run_doctor
from ideaforge.health import ServiceHealth


def test_collect_runtime_warnings_ffmpeg_for_merge(tmp_path: Path):
    cfg = IdeaForgeConfig(archive=tmp_path, merge_to_mp3=True, normalize_audio=False)
    with patch("ideaforge.config_validate._tool_on_path", return_value=None):
        warnings = collect_runtime_warnings(cfg)
    assert any("merge_to_mp3" in w for w in warnings)


def test_collect_runtime_warnings_diarize_without_hf(tmp_path: Path):
    cfg = IdeaForgeConfig(archive=tmp_path, diarize=True, hf_token=None)
    with (
        patch("ideaforge.config_validate._tool_on_path", return_value="/usr/bin/ffmpeg"),
        patch.dict("os.environ", {}, clear=True),
    ):
        # Keep PATH tools mocked; clear HF-related env
        warnings = collect_runtime_warnings(cfg)
    assert any("HF_TOKEN" in w or "diarize" in w for w in warnings)


def test_run_doctor_ok_with_defaults(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    archive.mkdir()
    cfg = IdeaForgeConfig(archive=archive, merge_to_mp3=False, normalize_audio=False)
    daemon = ServiceHealth("com.ideaforge.daemon", installed=True, running=True, pid=1)
    menubar = ServiceHealth("com.ideaforge.menubar", installed=True, running=True, pid=2)
    with (
        patch("ideaforge.doctor.check_daemon_health", return_value=daemon),
        patch("ideaforge.doctor.check_menubar_health", return_value=menubar),
        patch("ideaforge.doctor.platform.system", return_value="Darwin"),
        patch("ideaforge.config_validate._tool_on_path", return_value="/bin/true"),
        patch("ideaforge.config.has_xai_api_key", return_value=True),
    ):
        report = run_doctor(cfg, config_path=tmp_path / "missing.toml")
    assert report.ok
    text = format_doctor_report(report)
    assert "doctor" in text.lower()
    assert "archive" in text.lower()


def test_seed_last_notes_from_archive(tmp_path: Path):
    from ideaforge.status import load_last_notes, seed_last_notes_from_archive

    archive = tmp_path / "IdeaForge"
    date = archive / "2026-06-30"
    date.mkdir(parents=True)
    md = date / "20260630 - Standup.md"
    md.write_text("# notes", encoding="utf-8")
    store = tmp_path / "last_notes.json"

    notes = seed_last_notes_from_archive(archive, store_path=store, limit=3)
    assert len(notes) == 1
    assert notes[0].title == "Standup"
    # Second call does not overwrite
    md2 = date / "20260630 - Later.md"
    md2.write_text("# later", encoding="utf-8")
    again = seed_last_notes_from_archive(archive, store_path=store)
    assert len(again) == 1
    assert again[0].title == "Standup"
    assert load_last_notes(store)[0].title == "Standup"
