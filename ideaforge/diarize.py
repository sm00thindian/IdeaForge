"""Speaker diarization via pyannote — no re-transcription."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from ideaforge.audio_util import TARGET_SAMPLE_RATE, load_audio_mono_16k
from ideaforge.transcription_types import SpeakerTurn, TranscriptSegment


def _load_pipeline(hf_token: str) -> Any:
    from pyannote.audio import Pipeline  # type: ignore

    try:
        return Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token,
        )
    except TypeError:
        # Older pyannote/huggingface_hub API
        return Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )


def diarize_audio(audio_path: Path, hf_token: str) -> Optional[List[SpeakerTurn]]:
    """Run pyannote speaker diarization. Returns speaker turns or None on failure."""
    try:
        import torch  # type: ignore
    except ImportError:
        print("    ⚠️  torch not installed (pip install torch)")
        return None

    try:
        from pyannote.audio import Pipeline  # type: ignore  # noqa: F401
    except ImportError:
        print("    ⚠️  pyannote.audio not installed (pip install 'ideaforge[diarize]')")
        return None

    try:
        print("    🗣️  Running pyannote speaker diarization ...")
        pipeline = _load_pipeline(hf_token)

        # Bypass broken ffmpeg/torchcodec — feed waveform directly
        audio_np, _ = load_audio_mono_16k(audio_path)
        waveform = torch.from_numpy(audio_np).unsqueeze(0)
        diarization = pipeline({
            "waveform": waveform,
            "sample_rate": TARGET_SAMPLE_RATE,
        })

        turns: List[SpeakerTurn] = []
        for segment, _, speaker in diarization.itertracks(yield_label=True):
            turns.append(
                SpeakerTurn(
                    start=float(segment.start),
                    end=float(segment.end),
                    speaker=str(speaker),
                )
            )
        print(f"    ✓ Diarization complete ({len(turns)} speaker turns)")
        return turns
    except Exception as exc:
        print(f"    ⚠️  Diarization failed: {exc}")
        return None


def assign_speakers(
    segments: List[TranscriptSegment],
    turns: List[SpeakerTurn],
) -> List[TranscriptSegment]:
    """Assign speaker labels to transcript segments by temporal overlap."""
    if not turns:
        return segments

    labeled: List[TranscriptSegment] = []
    for seg in segments:
        speaker = _best_speaker_for_segment(seg.start, seg.end, turns)
        labeled.append(
            TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=speaker,
            )
        )
    return labeled


def _best_speaker_for_segment(
    start: float,
    end: float,
    turns: List[SpeakerTurn],
) -> str:
    best_speaker = "SPEAKER_UNKNOWN"
    best_overlap = 0.0
    seg_duration = max(end - start, 0.001)

    for turn in turns:
        overlap = _overlap(start, end, turn.start, turn.end)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker

    # Require at least 10% overlap to assign; otherwise unknown
    if best_overlap / seg_duration < 0.10:
        return "SPEAKER_UNKNOWN"
    return best_speaker


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))