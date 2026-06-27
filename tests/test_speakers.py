"""Tests for speaker renaming."""

from ideaforge.speakers import apply_speaker_map, format_diarized_transcript, rename_segments
from ideaforge.transcription_types import TranscriptSegment


def test_apply_speaker_map():
    assert apply_speaker_map("SPEAKER_00", {"SPEAKER_00": "Alex"}) == "Alex"
    assert apply_speaker_map("SPEAKER_99", {"SPEAKER_00": "Alex"}) == "SPEAKER_99"


def test_format_diarized_with_map():
    segments = [
        TranscriptSegment(start=0, end=1, text="Hello", speaker="SPEAKER_00"),
        TranscriptSegment(start=1, end=2, text="Hi back", speaker="SPEAKER_01"),
    ]
    text = format_diarized_transcript(segments, {"SPEAKER_00": "Kilynn", "SPEAKER_01": "Partner"})
    assert "[Kilynn]" in text
    assert "[Partner]" in text
    assert "SPEAKER_00" not in text


def test_rename_segments():
    segments = [TranscriptSegment(start=0, end=1, text="Hi", speaker="SPEAKER_02")]
    renamed = rename_segments(segments, {"SPEAKER_02": "Partner"})
    assert renamed[0].speaker == "Partner"