"""Transcription orchestration: mlx-whisper / faster-whisper + optional pyannote diarization."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ideaforge.backends import resolve_whisper_backend, transcribe_with_backend
from ideaforge.diarize import assign_speakers, diarize_audio
from ideaforge.transcription_types import TranscriptSegment, TranscriptionResult


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    *,
    whisper_backend: str = "auto",
    whisper_model: str = "small",
    whisper_device: str = "cpu",
    whisper_compute_type: str = "int8",
    beam_size: int = 1,
    diarize: bool = False,
    hf_token: Optional[str] = None,
    force: bool = False,
) -> Optional[Path]:
    """Transcribe audio and optionally diarize. Returns path to transcript (.txt)."""
    transcript_path = output_dir / f"{audio_path.stem}.txt"
    meta_path = output_dir / f"{audio_path.stem}_whisper.json"
    diarized_path = output_dir / f"{audio_path.stem}_diarized.json"

    if transcript_path.exists() and not force:
        if not diarize or diarized_path.exists():
            print("    ↳ Transcript exists → skipping")
            return transcript_path

    print(f"    🎙️  Transcribing {audio_path.name} ...")

    backend = resolve_whisper_backend(whisper_backend)
    result = transcribe_with_backend(
        audio_path,
        backend=backend,
        model_size=whisper_model,
        device=whisper_device,
        compute_type=whisper_compute_type,
        beam_size=beam_size,
    )

    diarized = False
    if diarize:
        if not hf_token:
            print("    ⚠️  HF_TOKEN required for pyannote diarization")
        else:
            turns = diarize_audio(audio_path, hf_token)
            if turns:
                result.segments = assign_speakers(result.segments, turns)
                diarized = True
                diarized_path.write_text(
                    json.dumps([s.to_dict() for s in result.segments], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(f"    ✓ Speaker labels assigned ({len(result.segments)} segments)")

    transcript_text = (
        _format_diarized_transcript(result.segments)
        if diarized
        else result.plain_text
    )
    transcript_path.write_text(transcript_text, encoding="utf-8")

    meta = {
        "audio_file": audio_path.name,
        "duration_seconds": round(result.duration_seconds, 1) if result.duration_seconds else None,
        "language": result.language,
        "transcribed_at": datetime.now().isoformat(timespec="seconds"),
        "backend": result.backend,
        "model": result.model,
        "diarized": diarized,
        "segment_count": len(result.segments),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"    ✓ Transcript saved ({len(transcript_text):,} chars)")
    return transcript_path


def _format_diarized_transcript(segments: List[TranscriptSegment]) -> str:
    lines: List[str] = []
    current_speaker: Optional[str] = None
    for seg in segments:
        speaker = seg.speaker or "SPEAKER_UNKNOWN"
        text = seg.text.strip()
        if not text:
            continue
        if speaker != current_speaker:
            lines.append(f"\n[{speaker}]")
            current_speaker = speaker
        lines.append(text)
    return "\n".join(lines).strip()