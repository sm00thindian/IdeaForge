"""Tests for pre-LLM transcript quality gate."""

from ideaforge.notify import ProcessResult, RecordingResult, format_completion_notification
from ideaforge.transcript_gate import (
    TranscriptGateSettings,
    assess_transcript_quality,
    strip_transcript_for_metrics,
)


def test_empty_transcript_rejected():
    result = assess_transcript_quality("")
    assert result.skip_llm
    assert "empty" in (result.reason or "")


def test_short_transcript_rejected():
    result = assess_transcript_quality(
        "um ok yeah",
        settings=TranscriptGateSettings(min_chars=5, min_words=8),
    )
    assert result.skip_llm
    assert "words" in (result.reason or "")


def test_normal_meeting_passes():
    text = (
        "SPEAKER_00: Good morning everyone. Let's review the sprint goals for this week. "
        "SPEAKER_01: I will send the design deck by Friday and update the roadmap. "
        "SPEAKER_00: Great, please also confirm the hiring timeline with HR."
    )
    result = assess_transcript_quality(text)
    assert result.ok
    assert result.word_count >= 8


def test_repetitive_junk_rejected():
    words = " ".join(["blah"] * 40)
    result = assess_transcript_quality(
        words,
        settings=TranscriptGateSettings(
            min_chars=10,
            min_words=8,
            min_words_for_junk_heuristics=12,
            max_repeat_word_ratio=0.65,
        ),
    )
    assert result.skip_llm
    assert "repetitive" in (result.reason or "")


def test_gate_disabled_always_ok():
    result = assess_transcript_quality("", settings=TranscriptGateSettings(enabled=False))
    assert result.ok


def test_strip_speaker_prefixes():
    text = "[SPEAKER_00]: Hello there\nSPEAKER_01: Hi back"
    cleaned = strip_transcript_for_metrics(text)
    assert "SPEAKER" not in cleaned.upper()
    assert "Hello" in cleaned


def test_notification_uses_skip_reason():
    result = ProcessResult(
        files_processed=1,
        recordings=[
            RecordingResult(
                stem="R2026-06-30-10-00-00",
                empty=True,
                skip_reason="transcript too short (3 words < 8)",
            )
        ],
    )
    _, subtitle, message = format_completion_notification(result, device_label="Z28")
    assert subtitle == "R2026-06-30-10-00-00"
    assert "Skipped LLM" in message
    assert "too short" in message
