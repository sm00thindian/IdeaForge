"""Shared types for transcription and diarization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text,
            **({"speaker": self.speaker} if self.speaker else {}),
        }


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@dataclass
class TranscriptionResult:
    segments: List[TranscriptSegment]
    language: Optional[str]
    duration_seconds: Optional[float]
    backend: str
    model: str
    plain_text: str = ""

    def __post_init__(self) -> None:
        if not self.plain_text:
            self.plain_text = "\n".join(
                seg.text.strip() for seg in self.segments if seg.text.strip()
            )