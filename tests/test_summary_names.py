"""Tests for friendly meeting note filenames."""

import json
from pathlib import Path

from ideaforge.summary_names import (
    date_prefix_for_session,
    friendly_summary_md_filename,
    plan_summary_md_path,
    recording_description_for_filename,
    refresh_friendly_summary_markdown,
    resolve_summary_md_path,
    sanitize_filename_component,
)


def test_sanitize_filename_component():
    assert sanitize_filename_component('Sync: API / "launch"') == "Sync - API launch"


def test_recording_description_uses_title():
    desc = recording_description_for_filename(
        title="Sprint Planning",
        session_stem="R2026-06-30-09-00-00",
        max_length=60,
    )
    assert desc == "Sprint Planning"


def test_recording_description_falls_back_to_action_preview():
    desc = recording_description_for_filename(
        title="R2026-06-30-09-00-00",
        session_stem="R2026-06-30-09-00-00",
        action_preview=["Alex: Send deck", "Jordan: Update roadmap"],
        max_length=80,
    )
    assert desc == "Alex - Send deck · Jordan - Update roadmap"


def test_recording_description_truncates_long_title_at_word_boundary():
    title = (
        "OMB M-21-31 Logging Requirements: NERC Data Architecture and "
        "AI Monitoring Options"
    )
    desc = recording_description_for_filename(title=title, max_length=60)
    assert len(desc) <= 60
    assert "NERC Data Architecture" in desc


def test_date_prefix_from_session_stem():
    assert (
        date_prefix_for_session(session_stem="R2026-06-30-09-00-00")
        == "20260630"
    )


def test_friendly_summary_md_filename_format():
    name = friendly_summary_md_filename(
        date_prefix="20260630",
        description="Sprint Planning",
    )
    assert name == "20260630 - Sprint Planning.md"


def test_plan_summary_md_path_avoids_collisions(tmp_path: Path):
    first = plan_summary_md_path(
        folder=tmp_path,
        session_stem="R2026-06-30-09-00-00",
        title="Sprint Planning",
        iso_date="2026-06-30",
    )
    first.write_text("# one", encoding="utf-8")
    second = plan_summary_md_path(
        folder=tmp_path,
        session_stem="R2026-06-30-10-00-00",
        title="Sprint Planning",
        iso_date="2026-06-30",
    )
    assert first.name == "20260630 - Sprint Planning.md"
    assert second.name == "20260630 - Sprint Planning (2).md"


def test_resolve_summary_md_path_prefers_metadata(tmp_path: Path):
    stem = "R2026-06-30-09-00-00"
    friendly = tmp_path / "20260630 - Sprint Planning.md"
    friendly.write_text("# notes", encoding="utf-8")
    json_path = tmp_path / f"{stem}_summary.json"
    json_path.write_text(
        json.dumps(
            {
                "title": "Sprint Planning",
                "metadata": {"summary_md": friendly.name},
            }
        ),
        encoding="utf-8",
    )
    assert resolve_summary_md_path(tmp_path, stem) == friendly


def test_refresh_friendly_summary_markdown_renames_legacy_file(tmp_path: Path):
    stem = "R2026-06-30-09-00-00"
    legacy = tmp_path / f"{stem}_summary.md"
    legacy.write_text("# Sprint Planning\n", encoding="utf-8")
    json_path = tmp_path / f"{stem}_summary.json"
    json_path.write_text(
        json.dumps(
            {
                "title": "Sprint Planning",
                "date": "2026-06-30",
                "action_items": [{"who": "Alex", "what": "Send deck"}],
                "metadata": {"session_stem": stem},
            }
        ),
        encoding="utf-8",
    )
    target = refresh_friendly_summary_markdown(json_path)
    assert target is not None
    assert target.name == "20260630 - Sprint Planning.md"
    assert target.read_text(encoding="utf-8") == "# Sprint Planning\n"
    assert not legacy.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["metadata"]["summary_md"] == target.name


def test_write_structured_output_uses_friendly_markdown_name(tmp_path: Path):
    from ideaforge.llm import _write_structured_output

    transcript = tmp_path / "R2026-06-30-09-00-00.txt"
    transcript.write_text("hello " * 20, encoding="utf-8")
    json_path = tmp_path / "R2026-06-30-09-00-00_summary.json"

    parsed = {
        "title": "Sprint Planning",
        "date": "2026-06-30",
        "executive_summary": "Quick sync on deliverables.",
        "action_items": [
            {"who": "Alex", "what": "Send deck"},
            {"who": "Jordan", "what": "Update roadmap"},
        ],
    }

    md_path = _write_structured_output(
        parsed,
        "meeting",
        tmp_path,
        json_path,
        "both",
        transcript,
        "grok",
        "grok-4.3",
    )

    assert md_path.name == "20260630 - Sprint Planning.md"
    assert md_path.is_file()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["metadata"]["summary_md"] == md_path.name
    assert data["metadata"]["session_stem"] == "R2026-06-30-09-00-00"