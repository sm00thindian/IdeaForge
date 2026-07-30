"""Rough stage ETAs from audio duration × real-time-factor baselines.

Constants mirror PERFORMANCE.md (Apple Silicon indicative values).
"""

from __future__ import annotations

from typing import Optional

# Wall-clock seconds per second of audio (RTF < 1 means faster than realtime).
RTF_TRANSCRIBE = 0.025  # mlx-whisper small ~1 min / 40 min audio
RTF_DIARIZE = 0.75  # pyannote mid-range of ~0.3–1.5

# Stage labels used in status.json (Stage.TRANSCRIBING / DIARIZING and step labels)
_STAGE_RTF = {
    "Transcribing": RTF_TRANSCRIBE,
    "Transcribe": RTF_TRANSCRIBE,
    "Diarizing": RTF_DIARIZE,
    "Diarize speakers": RTF_DIARIZE,
}


def rtf_for_stage(stage: Optional[str]) -> Optional[float]:
    if not stage:
        return None
    if stage in _STAGE_RTF:
        return _STAGE_RTF[stage]
    # Fuzzy match for "Transcribing …" style labels
    lowered = stage.lower()
    if "transcrib" in lowered:
        return RTF_TRANSCRIBE
    if "diariz" in lowered:
        return RTF_DIARIZE
    return None


def estimate_stage_seconds(
    *,
    stage: Optional[str] = None,
    audio_duration_seconds: Optional[float] = None,
    rtf: Optional[float] = None,
) -> Optional[float]:
    """Estimated total wall time for a stage on the full audio."""
    if audio_duration_seconds is None or audio_duration_seconds <= 0:
        return None
    factor = rtf if rtf is not None else rtf_for_stage(stage)
    if factor is None or factor <= 0:
        return None
    return float(audio_duration_seconds) * float(factor)


def estimate_remaining_seconds(
    *,
    stage: Optional[str] = None,
    audio_duration_seconds: Optional[float] = None,
    progress: Optional[float] = None,
    stage_elapsed_seconds: Optional[float] = None,
    rtf: Optional[float] = None,
) -> Optional[float]:
    """Rough remaining wall-clock seconds for the active stage.

    Prefer progress fraction when available; otherwise subtract stage elapsed
    from the total estimate.
    """
    total = estimate_stage_seconds(
        stage=stage,
        audio_duration_seconds=audio_duration_seconds,
        rtf=rtf,
    )
    if total is None:
        return None

    if progress is not None:
        try:
            p = float(progress)
        except (TypeError, ValueError):
            p = None
        else:
            if 0.0 <= p < 1.0:
                return max(0.0, total * (1.0 - p))
            if p >= 1.0:
                return 0.0

    if stage_elapsed_seconds is not None and stage_elapsed_seconds > 0:
        return max(0.0, total - float(stage_elapsed_seconds))

    return total


def format_eta_label(seconds: Optional[float]) -> Optional[str]:
    """Human label like ``~12m left`` (estimates only, no false precision)."""
    if seconds is None:
        return None
    total = max(0, int(round(seconds)))
    if total < 15:
        return "~moments left"
    if total < 60:
        # Round to 15s buckets
        bucket = max(15, int(round(total / 15.0) * 15))
        return f"~{bucket}s left"
    minutes = max(1, int(round(total / 60.0)))
    if minutes < 60:
        return f"~{minutes}m left"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"~{hours}h left"
    return f"~{hours}h {mins}m left"
