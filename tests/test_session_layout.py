"""Tests for date-folder + per-session archive layout helpers."""

from datetime import datetime, timedelta
from pathlib import Path

from ideaforge.ingest import prune_old_merged_wavs
from ideaforge.session_layout import (
    ensure_session_dir,
    find_summary_json,
    iter_session_dirs,
    iter_summary_json_files,
    iter_transcript_files,
    notes_dir_for_session,
    relocate_files_to_session_dir,
    resolve_date_folder,
    resolve_session_dir,
    session_artifact_paths,
    session_dir_for,
)


def test_session_dir_for_nests_under_date(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    assert session_dir_for(date, "R2026-07-20-09-00-00") == date / "R2026-07-20-09-00-00"


def test_resolve_session_dir_prefers_nested(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    nested = ensure_session_dir(date, "R2026-07-20-09-00-00")
    (nested / "R2026-07-20-09-00-00.txt").write_text("hi", encoding="utf-8")
    assert resolve_session_dir(date, "R2026-07-20-09-00-00") == nested


def test_resolve_session_dir_legacy_flat(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    date.mkdir()
    (date / "R2026-07-20-09-00-00.txt").write_text("hi", encoding="utf-8")
    assert resolve_session_dir(date, "R2026-07-20-09-00-00") == date


def test_resolve_session_dir_defaults_to_nested_for_new(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    date.mkdir()
    target = resolve_session_dir(date, "R2026-07-20-09-00-00")
    assert target == date / "R2026-07-20-09-00-00"


def test_notes_dir_is_date_folder_for_nested(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    session = ensure_session_dir(date, "R2026-07-20-09-00-00")
    assert notes_dir_for_session(session) == date


def test_notes_dir_is_self_for_flat(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    date.mkdir()
    assert notes_dir_for_session(date) == date


def test_resolve_date_folder_from_nested_file(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    session = ensure_session_dir(date, "R2026-07-20-09-00-00")
    wav = session / "R2026-07-20-09-00-00.WAV"
    wav.write_bytes(b"\x00" * 10)
    assert resolve_date_folder(wav) == date
    assert resolve_date_folder(session) == date


def test_relocate_files_to_session_dir(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    date.mkdir()
    a = date / "R2026-07-20-09-00-00.WAV"
    b = date / "R2026-07-20-09-15-00.WAV"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    session = ensure_session_dir(date, "R2026-07-20-09-00-00")
    moved = relocate_files_to_session_dir([a, b], session)
    assert all(p.parent == session for p in moved)
    assert not a.exists()
    assert (session / "R2026-07-20-09-00-00.WAV").is_file()


def test_iter_session_dirs_nested_and_flat(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    nested = ensure_session_dir(date, "R2026-07-20-09-00-00")
    (nested / "x.txt").write_text("x", encoding="utf-8")
    assert iter_session_dirs(date) == [nested]

    flat = tmp_path / "2026-07-21"
    flat.mkdir()
    (flat / "R2026-07-21-09-00-00.txt").write_text("y", encoding="utf-8")
    assert iter_session_dirs(flat) == [flat]


def test_iter_summary_and_transcript_nested(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    session = ensure_session_dir(date, "R2026-07-20-09-00-00")
    (session / "R2026-07-20-09-00-00_summary.json").write_text("{}", encoding="utf-8")
    (session / "R2026-07-20-09-00-00.txt").write_text("hello", encoding="utf-8")
    (date / "20260720 - Notes.md").write_text("# notes", encoding="utf-8")

    summaries = iter_summary_json_files(date)
    assert len(summaries) == 1
    assert summaries[0].parent == session

    transcripts = iter_transcript_files(date)
    assert len(transcripts) == 1
    assert transcripts[0].name == "R2026-07-20-09-00-00.txt"


def test_find_summary_json_nested_and_flat(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    session = ensure_session_dir(date, "R2026-07-20-09-00-00")
    nested_json = session / "R2026-07-20-09-00-00_summary.json"
    nested_json.write_text("{}", encoding="utf-8")
    assert find_summary_json(date, "R2026-07-20-09-00-00") == nested_json

    flat = tmp_path / "2026-07-21"
    flat.mkdir()
    flat_json = flat / "R2026-07-21-09-00-00_summary.json"
    flat_json.write_text("{}", encoding="utf-8")
    assert find_summary_json(flat, "R2026-07-21-09-00-00") == flat_json


def test_session_artifact_paths_points_md_at_date_root(tmp_path: Path):
    date = tmp_path / "2026-07-20"
    session = ensure_session_dir(date, "R2026-07-20-09-00-00")
    md = date / "20260720 - Meeting.md"
    md.write_text("# hi", encoding="utf-8")
    summary = session / "R2026-07-20-09-00-00_summary.json"
    summary.write_text(
        '{"metadata": {"summary_md": "20260720 - Meeting.md", "session_stem": "R2026-07-20-09-00-00"}}',
        encoding="utf-8",
    )
    paths = session_artifact_paths(session, "R2026-07-20-09-00-00")
    assert paths["summary_json"] == summary
    assert paths["notes_dir"] == date
    assert paths["summary_md"] == md


def test_prune_old_merged_wavs_finds_nested_session_files(tmp_path: Path):
    """Daily prune must still delete leftover merges under session packages."""
    import os

    now = datetime(2026, 7, 21, 3, 0, 0)
    date = tmp_path / "2026-07-10"
    session = ensure_session_dir(date, "R2026-07-10-09-00-00")
    merged = session / "R2026-07-10-09-00-00_merged.wav"
    merged.write_bytes(b"\x00" * 2048)

    old = (now - timedelta(days=5)).timestamp()
    os.utime(merged, (old, old))

    fresh_session = ensure_session_dir(tmp_path / "2026-07-20", "R2026-07-20-09-00-00")
    fresh = fresh_session / "R2026-07-20-09-00-00_merged.wav"
    fresh.write_bytes(b"\x00" * 2048)
    os.utime(fresh, ((now - timedelta(days=1)).timestamp(),) * 2)

    removed = prune_old_merged_wavs(tmp_path, retain_days=3, now=now)
    assert removed == [merged]
    assert not merged.exists()
    assert fresh.is_file()


def test_migrate_date_folder_moves_artifacts_keeps_notes(tmp_path: Path):
    from ideaforge.session_layout import migrate_date_folder_to_session_layout

    date = tmp_path / "2026-07-20"
    date.mkdir()
    wav = date / "R2026-07-20-09-00-00.WAV"
    txt = date / "R2026-07-20-09-00-00.txt"
    summary = date / "R2026-07-20-09-00-00_summary.json"
    note = date / "20260720 - Meeting.md"
    wav.write_bytes(b"\x00" * 10)
    txt.write_text("hello", encoding="utf-8")
    summary.write_text("{}", encoding="utf-8")
    note.write_text("# Meeting", encoding="utf-8")

    moves = migrate_date_folder_to_session_layout(date, dry_run=False)
    session = date / "R2026-07-20-09-00-00"
    assert session.is_dir()
    assert (session / wav.name).is_file()
    assert (session / txt.name).is_file()
    assert (session / summary.name).is_file()
    assert note.is_file()  # stays at date root
    assert len(moves) == 3


def test_migrate_groups_multi_chunk_wavs_with_merged(tmp_path: Path):
    """Continuation chunks + merged WAV share the first-chunk session package."""
    from ideaforge.session_layout import migrate_date_folder_to_session_layout

    date = tmp_path / "2026-07-02"
    date.mkdir()
    # Two long chunks that group_recordings should join (15 min, small gap).
    import wave
    import numpy as np

    def write_wav(path: Path, seconds: float = 600.0) -> None:
        rate = 12_000
        samples = np.zeros(int(rate * seconds), dtype=np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(samples.tobytes())

    # Filenames must match real recorder spacing (~15 min) for gap grouping.
    chunk_a = date / "R2026-07-02-09-00-00.WAV"
    chunk_b = date / "R2026-07-02-09-15-05.WAV"
    merged = date / "R2026-07-02-09-00-00_merged.wav"
    write_wav(chunk_a, 900.0)  # ends ~09:15:00; next starts 09:15:05 → gap ≤ 30s
    write_wav(chunk_b, 900.0)
    write_wav(merged, 1800.0)
    (date / "R2026-07-02-09-00-00.txt").write_text("hello", encoding="utf-8")
    (date / "20260702 - Notes.md").write_text("# notes", encoding="utf-8")

    migrate_date_folder_to_session_layout(date, dry_run=False)
    session = date / "R2026-07-02-09-00-00"
    assert (session / chunk_a.name).is_file()
    assert (session / chunk_b.name).is_file()
    assert (session / merged.name).is_file()
    assert (session / "R2026-07-02-09-00-00.txt").is_file()
    assert not (date / "R2026-07-02-09-15-05").exists()
    assert (date / "20260702 - Notes.md").is_file()
