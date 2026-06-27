"""Tests for LLM JSON parsing."""

from pathlib import Path

from ideaforge.llm import _dict_to_meeting, _parse_json_response


def test_parse_plain_json():
    raw = '{"title": "Test", "executive_summary": "Hello"}'
    parsed = _parse_json_response(raw)
    assert parsed is not None
    assert parsed["title"] == "Test"


def test_parse_fenced_json():
    raw = '```json\n{"title": "Fenced", "mode": "meeting"}\n```'
    parsed = _parse_json_response(raw)
    assert parsed is not None
    assert parsed["mode"] == "meeting"


def test_parse_invalid_returns_none():
    assert _parse_json_response("not json at all") is None


def test_dict_to_meeting_parses_speaker_identities():
    data = {
        "title": "Sync",
        "executive_summary": "Quick chat.",
        "speaker_identities": [
            {
                "speaker_id": "SPEAKER_00",
                "inferred_name": "Jordan",
                "confidence": "high",
                "rationale": "Said 'I'm Jordan'",
            }
        ],
        "speakers": [{"speaker": "Jordan (SPEAKER_00)", "summary": "Led discussion"}],
    }
    notes = _dict_to_meeting(data, Path("test.txt"))
    assert len(notes.speaker_identities) == 1
    assert notes.speaker_identities[0].inferred_name == "Jordan"
    assert notes.speakers[0].speaker == "Jordan (SPEAKER_00)"