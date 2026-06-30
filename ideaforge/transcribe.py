"""Transcription orchestration: mlx-whisper / faster-whisper + optional pyannote diarization."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ideaforge.audio_util import get_audio_duration_seconds
from ideaforge.backends import resolve_whisper_backend, transcribe_with_backend
from ideaforge.gpu_lock import gpu_stage
from ideaforge.diarize import assign_speakers, diarize_audio, load_cached_turns, save_turns_cache
from ideaforge.speakers import format_diarized_transcript, rename_segments
from ideaforge.status import Stage, StepId, active_reporter, status_touch
from ideaforge.transcription_types import TranscriptSegment, TranscriptionResult


def _paths_for_stem(output_dir: Path, stem: str) -> dict:
    return {
        "transcript": output_dir / f"{stem}.txt",
        "meta": output_dir / f"{stem}_whisper.json",
        "segments": output_dir / f"{stem}_segments.json",
        "turns": output_dir / f"{stem}_turns.json",
        "diarized": output_dir / f"{stem}_diarized.json",
    }


def _save_segments(path: Path, segments: List[TranscriptSegment]) -> None:
    path.write_text(
        json.dumps([s.to_dict() for s in segments], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_segments(path: Path) -> List[TranscriptSegment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        TranscriptSegment(
            start=float(item["start"]),
            end=float(item["end"]),
            text=item.get("text", ""),
            speaker=item.get("speaker"),
        )
        for item in data
    ]


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    *,
    whisper_backend: str = "auto",
    whisper_model: str = "small",
    whisper_device: str = "cpu",
    whisper_compute_type: str = "int8",
    beam_size: int = 1,
    language: Optional[str] = None,
    diarize: bool = False,
    hf_token: Optional[str] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    speaker_map: Optional[Dict[str, str]] = None,
    force: bool = False,
    output_stem: Optional[str] = None,
) -> Optional[Path]:
    """Transcribe audio and optionally diarize. Returns path to transcript (.txt)."""
    stem = output_stem or audio_path.stem
    paths = _paths_for_stem(output_dir, stem)
    transcript_path = paths["transcript"]

    if transcript_path.exists() and not force:
        if not diarize or paths["diarized"].exists():
            print("    ↳ Transcript exists → skipping")
            return transcript_path

    print(f"    🎙️  Transcribing {audio_path.name} ...")
    duration_hint = ""
    try:
        duration_seconds = get_audio_duration_seconds(audio_path)
        duration_hint = f"{int(duration_seconds // 60)} min audio"
    except OSError:
        duration_seconds = None
    status_touch(
        stage=Stage.TRANSCRIBING,
        clear_progress=True,
        detail=duration_hint or audio_path.name,
    )

    backend = resolve_whisper_backend(whisper_backend)
    with gpu_stage():
        result = transcribe_with_backend(
            audio_path,
            backend=backend,
            model_size=whisper_model,
            device=whisper_device,
            compute_type=whisper_compute_type,
            beam_size=beam_size,
            language=language,
            on_progress=lambda progress, detail: status_touch(
                stage=Stage.TRANSCRIBING,
                progress=progress,
                detail=detail,
            ),
        )

        _save_segments(paths["segments"], result.segments)

        if diarize:
            reporter = active_reporter()
            if reporter is not None:
                reporter.mark_step_done(StepId.TRANSCRIBE)
            result.segments = _apply_diarization(
                audio_path,
                result.segments,
                output_dir,
                hf_token=hf_token,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                speaker_map=speaker_map,
                force=force,
                output_stem=stem,
            )

    mapping = speaker_map or {}
    diarized = any(seg.speaker for seg in result.segments)
    transcript_text = (
        format_diarized_transcript(result.segments, mapping)
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
    paths["meta"].write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"    ✓ Transcript saved ({len(transcript_text):,} chars)")
    return transcript_path


def diarize_existing(
    audio_path: Path,
    output_dir: Path,
    *,
    hf_token: Optional[str] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    speaker_map: Optional[Dict[str, str]] = None,
    force: bool = False,
    output_stem: Optional[str] = None,
) -> Optional[Path]:
    """Diarize an existing transcription without re-transcribing."""
    stem = output_stem or audio_path.stem
    paths = _paths_for_stem(output_dir, stem)
    transcript_path = paths["transcript"]

    if paths["segments"].exists():
        segments = _load_segments(paths["segments"])
    elif paths["diarized"].exists():
        print(f"    ↳ Using {paths['diarized'].name} as segment source (legacy)")
        segments = [
            TranscriptSegment(start=s.start, end=s.end, text=s.text, speaker=None)
            for s in _load_segments(paths["diarized"])
        ]
        _save_segments(paths["segments"], segments)
    else:
        print(f"    ❌ Missing {paths['segments'].name} — run transcription first")
        return None

    if paths["diarized"].exists() and transcript_path.exists() and not force:
        print("    ↳ Diarized transcript exists → skipping")
        return transcript_path

    print(f"    🗣️  Diarizing {audio_path.name} (cached segments) ...")
    with gpu_stage():
        labeled = _apply_diarization(
            audio_path,
            segments,
            output_dir,
            hf_token=hf_token,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            speaker_map=speaker_map,
            force=force,
            output_stem=stem,
        )

    mapping = speaker_map or {}
    transcript_text = format_diarized_transcript(labeled, mapping)
    transcript_path.write_text(transcript_text, encoding="utf-8")
    print(f"    ✓ Diarized transcript saved ({len(transcript_text):,} chars)")
    return transcript_path


def _apply_diarization(
    audio_path: Path,
    segments: List[TranscriptSegment],
    output_dir: Path,
    *,
    hf_token: Optional[str],
    min_speakers: Optional[int],
    max_speakers: Optional[int],
    speaker_map: Optional[Dict[str, str]],
    force: bool,
    output_stem: Optional[str] = None,
) -> List[TranscriptSegment]:
    stem = output_stem or audio_path.stem
    paths = _paths_for_stem(output_dir, stem)

    if not hf_token:
        print("    ⚠️  HF_TOKEN required for pyannote diarization")
        return segments

    turns = None
    if paths["turns"].exists() and not force:
        turns = load_cached_turns(paths["turns"])
        if turns:
            print(f"    ↳ Using cached diarization ({len(turns)} turns)")

    if turns is None:
        turns = diarize_audio(
            audio_path,
            hf_token,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
        if turns:
            save_turns_cache(paths["turns"], turns, audio_path.name)

    if not turns:
        return segments

    def _label_progress(index: int, total: int) -> None:
        status_touch(
            stage=Stage.DIARIZING,
            progress=index / total if total else None,
            detail=f"Labeling segment {index}/{total}",
        )

    labeled = assign_speakers(segments, turns, on_progress=_label_progress)
    labeled = rename_segments(labeled, speaker_map or {})

    paths["diarized"].write_text(
        json.dumps([s.to_dict() for s in labeled], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"    ✓ Speaker labels assigned ({len(labeled)} segments)")
    reporter = active_reporter()
    if reporter is not None:
        reporter.mark_step_done(StepId.DIARIZE)
    return labeled