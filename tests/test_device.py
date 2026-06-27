"""Tests for USB recorder detection."""

from pathlib import Path

from ideaforge.device import RECORDING_PATTERN, is_recorder_volume


def test_recording_filename_pattern():
    assert RECORDING_PATTERN.match("R2026-06-27-07-43-11.WAV")
    assert RECORDING_PATTERN.match("r2026-01-01-00-00-00.wav")
    assert not RECORDING_PATTERN.match("meeting_notes.wav")


def test_is_recorder_volume_with_record_folder(tmp_path: Path):
    record = tmp_path / "RECORD"
    record.mkdir()
    (record / "R2026-06-27-07-43-11.WAV").write_bytes(b"\x00" * 1000)
    assert is_recorder_volume(tmp_path)


def test_is_recorder_volume_with_recset_only(tmp_path: Path):
    (tmp_path / "recset.txt").write_text("BIT:2\n")
    assert is_recorder_volume(tmp_path)


def test_is_not_recorder_volume(tmp_path: Path):
    (tmp_path / "random.txt").write_text("hello")
    assert not is_recorder_volume(tmp_path)