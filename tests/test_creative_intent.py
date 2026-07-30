"""Tests for creative intent detection."""

from ideaforge.config import CreativeSettings
from ideaforge.creative_intent import (
    SUMMARIZE_LABEL_SONG_IDEA,
    detect_intent,
    is_song_idea,
    resolve_summarize_context,
)


def test_detects_song_idea_at_start():
    transcript = (
        "Song idea. I want a lo-fi folk song about fireflies on the porch. "
        "Chorus: dancing in the summer light."
    )
    result = detect_intent(transcript, ["song idea", "lyric idea"])
    assert is_song_idea(result)
    assert result.matched_phrase == "song idea"
    assert "fireflies" in result.content_after_trigger


def test_detects_after_yeah_and_write_a_song():
    """Real failure: Whisper heard 'Yeah. Write a song about…' without 'song idea'."""
    transcript = (
        "[SPEAKER_00]\n"
        "Yeah. Write a song about losing your way, not having any purpose, "
        "and focusing on yourself, traveling and discovering yourself."
    )
    result = detect_intent(transcript, ["song idea", "lyric idea"])
    assert is_song_idea(result)
    assert result.matched_phrase is not None
    assert "losing your way" in result.content_after_trigger.lower()


def test_detects_song_idea_after_fillers_and_speaker_label():
    transcript = "[SPEAKER_00]\nUm, okay, song idea. Folk about the river at night."
    result = detect_intent(transcript, ["song idea"])
    assert is_song_idea(result)
    assert result.matched_phrase == "song idea"
    assert "river" in result.content_after_trigger.lower()


def test_ignores_trigger_late_in_transcript():
    transcript = (
        "We discussed the roadmap for an hour. "
        "Someone joked about a song idea for the marketing video."
    )
    result = detect_intent(transcript, ["song idea"], scan_chars=80)
    assert not is_song_idea(result)


def test_meeting_when_no_trigger():
    result = detect_intent("Quick sync on Q3 priorities and hiring.", ["song idea"])
    assert not is_song_idea(result)


def test_longer_phrase_wins():
    transcript = "Lyric idea for a ballad about leaving home."
    result = detect_intent(transcript, ["song idea", "lyric idea"])
    assert result.matched_phrase == "lyric idea"


def test_resolve_summarize_context_auto_detects_song_idea():
    settings = CreativeSettings(trigger_phrases=["song idea"])
    intent, label = resolve_summarize_context(
        "Song idea. Folk ballad about the river.",
        "auto",
        settings,
    )
    assert intent == "song_idea"
    assert label == SUMMARIZE_LABEL_SONG_IDEA


def test_resolve_summarize_context_meeting_mode():
    settings = CreativeSettings(trigger_phrases=["song idea"])
    intent, label = resolve_summarize_context(
        "Song idea. This should still be meeting mode.",
        "meeting",
        settings,
    )
    assert intent == "meeting"
    assert label == "Meeting notes"