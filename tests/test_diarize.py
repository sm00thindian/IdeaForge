"""Tests for speaker assignment logic."""

from ideaforge.diarize import assign_speakers, _overlap
from ideaforge.transcription_types import SpeakerTurn, TranscriptSegment


def test_overlap_calculation():
    assert _overlap(0, 10, 5, 15) == 5
    assert _overlap(0, 5, 10, 15) == 0


def test_assign_speakers_by_overlap():
    segments = [
        TranscriptSegment(start=0, end=5, text="Hello everyone"),
        TranscriptSegment(start=5, end=10, text="Thanks for joining"),
    ]
    turns = [
        SpeakerTurn(start=0, end=6, speaker="SPEAKER_00"),
        SpeakerTurn(start=6, end=12, speaker="SPEAKER_01"),
    ]
    labeled = assign_speakers(segments, turns)
    assert labeled[0].speaker == "SPEAKER_00"
    assert labeled[1].speaker == "SPEAKER_01"


def test_assign_unknown_when_low_overlap():
    segments = [TranscriptSegment(start=0, end=1, text="Hi")]
    turns = [SpeakerTurn(start=10, end=20, speaker="SPEAKER_00")]
    labeled = assign_speakers(segments, turns)
    assert labeled[0].speaker == "SPEAKER_UNKNOWN"