"""Tests for prompt building."""

from ideaforge.prompts import (
    build_meeting_system_prompt,
    build_prompt,
    format_recording_context,
    meeting_domain_examples,
    transcript_has_speaker_labels,
)


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
    # General domain: no forced Fed/GRC framing
    assert "Federal Reserve" not in system
    assert "discussion_topics" in user
    assert "preparation_notes" in user


def test_meeting_domain_fed_grc_pack():
    system, _ = build_prompt(
        "meeting",
        "We discussed the SSP and POA&M.",
        meeting_domain="fed_grc",
    )
    assert "OSCAL" in system
    assert "meeting scribe" in system.lower() or "executive assistant" in system.lower()


def test_meeting_prompt_without_speakers():
    _, user = build_prompt("meeting", "Solo voice memo about project tasks.")
    assert "no" in user.lower()
    assert "Unattributed" in user


def test_general_examples_are_neutral():
    examples = meeting_domain_examples("general")
    assert "FedNow" not in examples["action_notes_example"]
    assert "Zacta" not in examples["prep_notes_example"]
    assert "OSCAL" not in examples["artifact_rule"]
    _, user = build_prompt("meeting", "Quick sync on hiring.", meeting_domain="general")
    assert "FedNow" not in user
    assert "Zacta" not in user
    assert "release checklist" in user or "design review" in user


def test_fed_grc_examples_mention_domain_carefully():
    examples = meeting_domain_examples("fed_grc")
    assert "control" in examples["action_notes_example"].lower() or "ticket" in examples[
        "action_notes_example"
    ].lower()
    _, user = build_prompt(
        "meeting",
        "We discussed the SSP.",
        meeting_domain="fed_grc",
    )
    assert "do not invent OSCAL" in user.lower() or "OSCAL" in user


def test_recording_date_injected_for_relative_resolution():
    _, user = build_prompt(
        "meeting",
        "Let's ship tomorrow and sync next Wednesday.",
        recording_date="2026-07-30",
        recording_date_source="filename",
    )
    assert "2026-07-30" in user
    assert "filename" in user
    assert "YYYY-MM-DD" in user
    assert "tomorrow" in user.lower()


def test_recording_context_when_missing():
    text = format_recording_context(recording_date=None)
    assert "no authoritative recording date" in text.lower()


def test_meeting_type_guidance_present():
    _, user = build_prompt("meeting", "Daily standup: no blockers.")
    assert "standup" in user.lower()
    assert "voice_memo" in user.lower()
    assert "1:1" in user
    assert "Meeting-type guidance" in user or "meeting-type guidance" in user.lower()


def test_general_system_has_no_fed_pack():
    system = build_meeting_system_prompt("general")
    assert "OSCAL" not in system
    assert "Federal Reserve" not in system
