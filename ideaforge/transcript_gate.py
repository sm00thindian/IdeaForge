"""Skip low-value transcripts before expensive LLM summarization."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional


# Speaker labels from diarization / formatted transcripts
_SPEAKER_PREFIX = re.compile(
    r"^\s*(?:\[?SPEAKER[_\s]?\d+\]?|[A-Za-z][A-Za-z0-9 ._-]{0,40})\s*:\s*",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9\s']+")


@dataclass(frozen=True)
class TranscriptGateSettings:
    """Thresholds for pre-LLM transcript quality checks."""

    enabled: bool = True
    min_chars: int = 40
    min_words: int = 8
    # Fraction of words that are the single most common token (0 disables).
    max_repeat_word_ratio: float = 0.65
    # Unique words / total words floor for longer transcripts (0 disables).
    min_unique_word_ratio: float = 0.12
    # Only apply uniqueness/repeat checks when word count is at least this.
    min_words_for_junk_heuristics: int = 12


@dataclass(frozen=True)
class TranscriptGateResult:
    """Outcome of a quality check."""

    ok: bool
    reason: Optional[str] = None
    char_count: int = 0
    word_count: int = 0

    @property
    def skip_llm(self) -> bool:
        return not self.ok


def strip_transcript_for_metrics(text: str) -> str:
    """Remove speaker prefixes and collapse whitespace for counting."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = _SPEAKER_PREFIX.sub("", raw).strip()
        if line:
            lines.append(line)
    cleaned = " ".join(lines) if lines else text.strip()
    cleaned = _NON_ALNUM.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def word_tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def assess_transcript_quality(
    text: str,
    settings: Optional[TranscriptGateSettings] = None,
) -> TranscriptGateResult:
    """Return whether the transcript is worth sending to the LLM.

    Empty / near-empty / highly repetitive content is rejected so we do not
    spend API cost or produce junk notes. Intentional skips are not failures.
    """
    cfg = settings or TranscriptGateSettings()
    if not cfg.enabled:
        stripped = (text or "").strip()
        words = word_tokens(strip_transcript_for_metrics(stripped))
        return TranscriptGateResult(
            ok=True,
            char_count=len(stripped),
            word_count=len(words),
        )

    raw = (text or "").strip()
    if not raw:
        return TranscriptGateResult(
            ok=False,
            reason="empty transcript",
            char_count=0,
            word_count=0,
        )

    metrics_text = strip_transcript_for_metrics(raw)
    char_count = len(metrics_text)
    words = word_tokens(metrics_text)
    word_count = len(words)

    if char_count < cfg.min_chars:
        return TranscriptGateResult(
            ok=False,
            reason=f"transcript too short ({char_count} chars < {cfg.min_chars})",
            char_count=char_count,
            word_count=word_count,
        )
    if word_count < cfg.min_words:
        return TranscriptGateResult(
            ok=False,
            reason=f"transcript too short ({word_count} words < {cfg.min_words})",
            char_count=char_count,
            word_count=word_count,
        )

    if word_count >= cfg.min_words_for_junk_heuristics and words:
        counts = Counter(words)
        top_word, top_count = counts.most_common(1)[0]
        # Ignore ultra-common stop words for pure repetition (uh/um still count)
        if cfg.max_repeat_word_ratio > 0:
            ratio = top_count / word_count
            if ratio >= cfg.max_repeat_word_ratio and top_word not in {
                "the",
                "a",
                "and",
                "to",
                "of",
                "i",
                "you",
                "it",
            }:
                return TranscriptGateResult(
                    ok=False,
                    reason=(
                        f"repetitive transcript "
                        f"({top_word!r} is {ratio:.0%} of words)"
                    ),
                    char_count=char_count,
                    word_count=word_count,
                )

        if cfg.min_unique_word_ratio > 0:
            unique_ratio = len(counts) / word_count
            if unique_ratio < cfg.min_unique_word_ratio:
                return TranscriptGateResult(
                    ok=False,
                    reason=(
                        f"low-information transcript "
                        f"({unique_ratio:.0%} unique words)"
                    ),
                    char_count=char_count,
                    word_count=word_count,
                )

    return TranscriptGateResult(
        ok=True,
        char_count=char_count,
        word_count=word_count,
    )
