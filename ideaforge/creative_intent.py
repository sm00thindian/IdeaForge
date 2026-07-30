"""Keyword-based intent detection for creative routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from ideaforge.config import CreativeSettings

_INTENT_MEETING = "meeting"
_INTENT_SONG_IDEA = "song_idea"

# Leading noise Whisper often puts before the real trigger.
_SPEAKER_LABEL = re.compile(r"^\[SPEAKER_\d+\]\s*", re.IGNORECASE | re.MULTILINE)
# Word-boundary after each filler so "so" does not eat the start of "Song".
_LEADING_FILLERS = re.compile(
    r"^(?:"
    r"(?:yeah|yep|yes|yup|ok|okay|so|well|um+|uh+|ah+|oh|hey|hi|hello|alright|all\s+right|"
    r"like|right|listen|look|anyway)\b"
    r"[\s,.\-!?:;…]*"
    r")+",
    re.IGNORECASE,
)
# Extra built-in phrases beyond user config (still require near-start after fillers).
_BUILTIN_TRIGGERS = (
    "song idea",
    "lyric idea",
    "write a song",
    "write me a song",
    "make a song",
    "new song",
    "here's a song idea",
    "this is a song idea",
)


@dataclass(frozen=True)
class IntentResult:
    intent: str
    matched_phrase: Optional[str] = None
    content_after_trigger: str = ""


def _normalize_head(transcript: str, scan_chars: int) -> str:
    """Speaker labels + fillers stripped; collapse whitespace for matching."""
    text = transcript.strip()
    if not text:
        return ""
    # Work on the head of the recording only.
    head = text[: max(scan_chars, 50)]
    # Drop diarization labels (including alone on a line).
    head = _SPEAKER_LABEL.sub("", head)
    head = re.sub(r"\s+", " ", head).strip()
    # Drop verbal fillers so "Yeah. Song idea…" still matches.
    for _ in range(4):
        cleaned = _LEADING_FILLERS.sub("", head).strip()
        if cleaned == head:
            break
        head = cleaned
    return head


def detect_intent(
    transcript: str,
    trigger_phrases: Sequence[str],
    *,
    scan_chars: int = 500,
) -> IntentResult:
    """
    Detect song-idea intent when a trigger phrase opens the recording.

    Matching is case-insensitive and ignores:
    - leading ``[SPEAKER_XX]`` labels (including on their own line)
    - common fillers (yeah, um, so, okay, …)
    - punctuation between filler and the phrase

    ``scan_chars`` limits how much of the start of the transcript is considered
    (so a late joke "song idea" does not re-route a meeting).
    """
    if not transcript.strip():
        return IntentResult(intent=_INTENT_MEETING)

    phrases = [p.strip() for p in trigger_phrases if p and str(p).strip()]
    # Always include built-ins; user phrases take priority by length when sorted.
    for builtin in _BUILTIN_TRIGGERS:
        if builtin not in {p.lower() for p in phrases}:
            phrases.append(builtin)

    if not phrases:
        return IntentResult(intent=_INTENT_MEETING)

    head = _normalize_head(transcript, scan_chars)
    if not head:
        return IntentResult(intent=_INTENT_MEETING)

    ordered = sorted(phrases, key=len, reverse=True)
    for phrase in ordered:
        # Word boundary after phrase so "song ideas" still matches "song idea".
        pattern = re.compile(
            rf"^{re.escape(phrase)}(?:\b|(?=s\b)|(?=[\s,.\-!?:;…]))",
            re.IGNORECASE,
        )
        match = pattern.match(head)
        if not match:
            # Also allow "…: song idea" / soft punctuation already stripped
            continue
        after = head[match.end() :].strip()
        after = re.sub(r"^[,.\s:;!?…\-]+", "", after)
        # Prefer original transcript tail when possible for content fidelity
        full = transcript.strip()
        # Best-effort: strip trigger region from original for content_after
        content = after
        return IntentResult(
            intent=_INTENT_SONG_IDEA,
            matched_phrase=phrase,
            content_after_trigger=content or full,
        )

    # Fallback: clear "write a song about …" anywhere in the scan window
    # after fillers (common when user skips the ritual phrase).
    soft = re.compile(
        r"\b(?:write|make|compose|draft)\s+(?:me\s+)?(?:a\s+)?song\b",
        re.IGNORECASE,
    )
    soft_match = soft.search(head)
    if soft_match and soft_match.start() < 80:
        after = head[soft_match.end() :].strip()
        after = re.sub(r"^[,.\s:;!?…\-]+", "", after)
        return IntentResult(
            intent=_INTENT_SONG_IDEA,
            matched_phrase=soft_match.group(0).lower(),
            content_after_trigger=after or head,
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
