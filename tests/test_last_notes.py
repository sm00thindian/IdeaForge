"""Tests for last-run markdown notes links (menubar + status store)."""

from pathlib import Path

from ideaforge.notify import RecordingResult
from ideaforge.status import (
    LastNote,
    clear_last_notes,
    last_notes_from_recordings,
    load_last_notes,
    record_last_notes_from_recordings,
    save_last_notes,
)


def test_save_and_load_last_notes(tmp_path: Path):
    md = tmp_path / "20260630 - Standup.md"
    md.write_text("# notes", encoding="utf-8")
    store = tmp_path / "last_notes.json"

    save_last_notes(
        [LastNote(path=str(md), title="Standup", output_intent=None, stem="R1")],
        path=store,
    )
    loaded = load_last_notes(store)
    assert len(loaded) == 1
    assert loaded[0].title == "Standup"
    assert Path(loaded[0].path) == md.resolve()


def test_load_last_notes_drops_missing_files(tmp_path: Path):
    md = tmp_path / "gone.md"
    store = tmp_path / "last_notes.json"
    save_last_notes(
        [LastNote(path=str(md), title="Gone")],
        path=store,
    )
    assert load_last_notes(store) == []


def test_record_last_notes_replaces_previous(tmp_path: Path):
    store = tmp_path / "last_notes.json"
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    save_last_notes([LastNote(path=str(first), title="Old")], path=store)
    record_last_notes_from_recordings(
        [
            RecordingResult(
                stem="R2",
                title="New meeting",
                summary_md=str(second),
            )
        ],
        path=store,
    )
    loaded = load_last_notes(store)
    assert len(loaded) == 1
    assert loaded[0].title == "New meeting"
    assert Path(loaded[0].path) == second.resolve()


def test_record_last_notes_skips_empty_run(tmp_path: Path):
    store = tmp_path / "last_notes.json"
    keep = tmp_path / "keep.md"
    keep.write_text("x", encoding="utf-8")
    save_last_notes([LastNote(path=str(keep), title="Keep")], path=store)

    record_last_notes_from_recordings(
        [RecordingResult(stem="R3", skipped=True)],
        path=store,
    )
    loaded = load_last_notes(store)
    assert len(loaded) == 1
    assert loaded[0].title == "Keep"


def test_last_notes_from_recordings_filters_and_labels(tmp_path: Path):
    meeting = tmp_path / "meeting.md"
    song = tmp_path / "song.md"
    missing = tmp_path / "missing.md"
    meeting.write_text("m", encoding="utf-8")
    song.write_text("s", encoding="utf-8")

    notes = last_notes_from_recordings(
        [
            RecordingResult(stem="a", title="Standup", summary_md=str(meeting)),
            RecordingResult(
                stem="b",
                title="Chorus hook",
                summary_md=str(song),
                output_intent="song_idea",
            ),
            RecordingResult(stem="c", title="Gone", summary_md=str(missing)),
            RecordingResult(stem="d", empty=True, summary_md=str(meeting)),
            RecordingResult(stem="e", failed=True, summary_md=str(meeting)),
        ]
    )
    assert [n.title for n in notes] == ["Standup", "Chorus hook"]
    assert notes[1].menu_label.startswith("🎵")


def test_clear_last_notes(tmp_path: Path):
    store = tmp_path / "last_notes.json"
    md = tmp_path / "n.md"
    md.write_text("n", encoding="utf-8")
    save_last_notes([LastNote(path=str(md), title="N")], path=store)
    clear_last_notes(store)
    assert load_last_notes(store) == []


def test_song_menu_label():
    note = LastNote(path="/tmp/x.md", title="Blue skies", output_intent="song_idea")
    assert note.menu_label == "🎵 Blue skies"
