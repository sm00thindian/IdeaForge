"""Speaker labeling, renaming, and transcript formatting."""

from __future__ import annotations

from typing import Dict, List, Optional

from ideaforge.transcription_types import TranscriptSegment


def apply_speaker_map(label: Optional[str], speaker_map: Dict[str, str]) -> str:
    """Map pyannote labels (SPEAKER_00) to friendly names."""
    if not label:
        return "SPEAKER_UNKNOWN"
    return speaker_map.get(label, label)


def rename_segments(
    segments: List[TranscriptSegment],
    speaker_map: Dict[str, str],
) -> List[TranscriptSegment]:
    if not speaker_map:
        return segments
    return [
        TranscriptSegment(
            start=seg.start,
            end=seg.end,
            text=seg.text,
            speaker=apply_speaker_map(seg.speaker, speaker_map),
        )
        for seg in segments
    ]


def format_diarized_transcript(
    segments: List[TranscriptSegment],
    speaker_map: Optional[Dict[str, str]] = None,
) -> str:
    """Render segments as [Speaker] blocks."""
    mapping = speaker_map or {}
    lines: List[str] = []
    current_speaker: Optional[str] = None

    for seg in segments:
        speaker = apply_speaker_map(seg.speaker, mapping)
        text = seg.text.strip()
        if not text:
            continue
        if speaker != current_speaker:
            lines.append(f"\n[{speaker}]")
            current_speaker = speaker
        lines.append(text)

    return "\n".join(lines).strip()