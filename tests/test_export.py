"""Tests for action item export."""

import json
from pathlib import Path
from unittest.mock import patch

from ideaforge.export import (
    ExportSettings,
    action_item_fingerprint,
    export_action_items,
    format_obsidian_section,
    meeting_notes_from_json,
)
from ideaforge.schema import ActionItem, MeetingNotes


def _notes(**kwargs) -> MeetingNotes:
    defaults = {
        "title": "Sprint Planning",
        "date": "2026-06-27",
        "executive_summary": "Quick sync.",
        "action_items": [
            ActionItem(
                who="Alex",
                what="Send deck",
                when="Friday",
                priority="high",
                confidence="explicit",
                source_quote="I'll send the deck Friday",
            )
        ],
    }
    defaults.update(kwargs)
    return MeetingNotes(**defaults)


def test_action_item_fingerprint_stable():
    item = ActionItem(who="Alex", what="Send deck", when="Friday")
    a = action_item_fingerprint(item, meeting_title="Sync", recording_stem="rec")
    b = action_item_fingerprint(item, meeting_title="Sync", recording_stem="rec")
    assert a == b


def test_format_obsidian_section():
    md = format_obsidian_section(
        _notes().action_items,
        notes=_notes(),
        recording_stem="R2026-06-27-07-43-11",
    )
    assert "## Sprint Planning" in md
    assert "- [ ] **Alex:** Send deck" in md
    assert "priority:: high" in md
    assert "[[R2026-06-27-07-43-11]]" in md


def test_export_to_obsidian_creates_note(tmp_path: Path):
    vault = tmp_path / "Vault"
    vault.mkdir()
    archive = tmp_path / "Archive"
    settings = ExportSettings(
        obsidian=True,
        obsidian_vault=vault,
        obsidian_note="IdeaForge/Action Items.md",
    )
    count = export_action_items(
        _notes(),
        archive=archive,
        recording_stem="R2026-06-27-07-43-11",
        settings=settings,
    )
    note = vault / "IdeaForge" / "Action Items.md"
    assert count == 1
    assert note.exists()
    assert "Alex" in note.read_text()


def test_export_dedup_skips_second_run(tmp_path: Path):
    vault = tmp_path / "Vault"
    vault.mkdir()
    archive = tmp_path / "Archive"
    settings = ExportSettings(
        obsidian=True,
        obsidian_vault=vault,
        obsidian_note="Action Items.md",
    )
    export_action_items(
        _notes(),
        archive=archive,
        recording_stem="rec",
        settings=settings,
    )
    second = export_action_items(
        _notes(),
        archive=archive,
        recording_stem="rec",
        settings=settings,
    )
    assert second == 0


def test_meeting_notes_from_json(tmp_path: Path):
    path = tmp_path / "rec_summary.json"
    path.write_text(
        json.dumps({
            "title": "Sync",
            "date": "2026-06-27",
            "executive_summary": "Hi",
            "action_items": [{"who": "Alex", "what": "Follow up"}],
        }),
        encoding="utf-8",
    )
    notes = meeting_notes_from_json(path)
    assert notes.title == "Sync"
    assert len(notes.action_items) == 1


def test_export_reminders_calls_osascript(tmp_path: Path):
    archive = tmp_path / "Archive"
    settings = ExportSettings(reminders=True, reminders_list="IdeaForge")
    with patch("ideaforge.export.platform.system", return_value="Darwin"), patch(
        "ideaforge.export.subprocess.run",
    ) as run:
        run.return_value.returncode = 0
        count = export_action_items(
            _notes(),
            archive=archive,
            recording_stem="rec",
            settings=settings,
        )
    assert count == 1
    run.assert_called_once()