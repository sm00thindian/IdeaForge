"""Tests for diarization turn caching."""

import json
from pathlib import Path

from ideaforge.diarize import load_cached_turns, save_turns_cache
from ideaforge.transcription_types import SpeakerTurn


def test_turns_cache_roundtrip(tmp_path: Path):
    path = tmp_path / "turns.json"
    turns = [
        SpeakerTurn(start=0.0, end=1.5, speaker="SPEAKER_00"),
        SpeakerTurn(start=1.5, end=3.0, speaker="SPEAKER_01"),
    ]
    save_turns_cache(path, turns, "test.wav")
    loaded = load_cached_turns(path)
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0].speaker == "SPEAKER_00"
    assert loaded[1].end == 3.0