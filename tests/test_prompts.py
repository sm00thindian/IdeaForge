"""Tests for prompt building."""

from ideaforge.prompts import build_prompt, transcript_has_speaker_labels


def test_transcript_has_speaker_labels():
    assert transcript_has_speaker_labels("[SPEAKER_00]\nHello there")
    assert not transcript_has_speaker_labels("Hello there, no labels")


def test_meeting_prompt_includes_speaker_context():
    _, user = build_prompt("meeting", "[SPEAKER_00]\nWe decided to ship Friday.")
    assert "yes" in user.lower()
    assert "SPEAKER" in user
    assert "speaker_identities" in user


def test_meeting_prompt_infers_names_instruction():
    system, user = build_prompt("meeting", "[SPEAKER_00]\nHi, I'm Jordan.")
    assert "infer" in system.lower()
    assert "speaker_identities" in system.lower()
    assert "action_items" in user.lower() or "action item" in user.lower()
    assert "never raw SPEAKER_XX" in user


def test_meeting_prompt_without_speakers():
    _, user = build_prompt("meeting", "Solo voice memo about project tasks.")
    assert "no" in user.lower()
    assert "Unattributed" in user