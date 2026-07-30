"""Keyword-based intent detection for creative routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from ideaforge.config import CreativeSettings

_INTENT_MEETING = "meeting"
_INTENT_SONG_IDEA = "song_idea"


@dataclass(frozen=True)
class IntentResult:
    intent: str
    matched_phrase: Optional[str] = None
    content_after_trigger: str = ""


def detect_intent(
    transcript: str,
    trigger_phrases: Sequence[str],
    *,
    scan_chars: int = 500,
) -> IntentResult:
    """
    Detect song-idea intent when a trigger phrase opens the recording.

    The phrase must appear at the start of the transcript (after an optional
    ``[SPEAKER_XX]`` label). ``scan_chars`` limits how much audio is considered
    when stripping the trigger to recover memo content.
    """
    if not transcript.strip() or not trigger_phrases:
        return IntentResult(intent=_INTENT_MEETING)

    text = transcript.strip()
    ordered = sorted(
        (p.strip() for p in trigger_phrases if p and p.strip()),
        key=len,
        reverse=True,
    )

    for phrase in ordered:
        pattern = re.compile(
            rf"^(?:\[SPEAKER_\d+\]\s*)?{re.escape(phrase)}\b",
            re.IGNORECASE,
        )
        match = pattern.match(text)
        if not match:
            continue
        after = text[match.end() :].strip()
        after = re.sub(r"^[,.\s:;!?-]+", "", after)
        return IntentResult(
            intent=_INTENT_SONG_IDEA,
            matched_phrase=phrase,
            content_after_trigger=after,
        )

    return IntentResult(intent=_INTENT_MEETING)


def is_song_idea(result: IntentResult) -> bool:
    return result.intent == _INTENT_SONG_IDEA


SUMMARIZE_LABEL_MEETING = "Meeting notes"
SUMMARIZE_LABEL_SONG_IDEA = "Song idea"


def resolve_summarize_context(
    transcript: str,
    mode: str,
    creative_settings: Optional["CreativeSettings"],
) -> Tuple[str, str]:
    """
    Return ``(output_intent, summarize_step_label)`` for status UI and notifications.

    ``output_intent`` is ``song_idea`` or ``meeting``.
    """
    if mode == "creative":
        return _INTENT_SONG_IDEA, SUMMARIZE_LABEL_SONG_IDEA
    if mode == "meeting":
        return _INTENT_MEETING, SUMMARIZE_LABEL_MEETING
    if mode == "auto" and creative_settings and creative_settings.enabled:
        result = detect_intent(
            transcript,
            creative_settings.trigger_phrases,
            scan_chars=creative_settings.scan_chars,
        )
        if is_song_idea(result):
            return _INTENT_SONG_IDEA, SUMMARIZE_LABEL_SONG_IDEA
    return _INTENT_MEETING, SUMMARIZE_LABEL_MEETING