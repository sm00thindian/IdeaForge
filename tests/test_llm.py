"""Tests for LLM JSON parsing."""

from ideaforge.llm import _parse_json_response


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