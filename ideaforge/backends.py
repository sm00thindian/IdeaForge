"""Transcription backends: mlx-whisper (Apple Silicon) and faster-whisper (fallback)."""

from __future__ import annotations

import platform
from typing import List, Optional

from ideaforge.audio_util import get_audio_duration_seconds, load_audio_mono_16k
from ideaforge.transcription_types import TranscriptSegment, TranscriptionResult

MLX_MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}


def mlx_available() -> bool:
    try:
        import mlx_whisper  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def faster_whisper_available() -> bool:
    try:
        from faster_whisper import WhisperModel  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def resolve_whisper_backend(requested: str = "auto") -> str:
    """Pick transcription backend: mlx on Apple Silicon when available, else faster-whisper."""
    if requested in ("mlx", "faster"):
        if requested == "mlx" and not mlx_available():
            print("    ⚠️  mlx-whisper not installed — falling back to faster-whisper")
            return "faster"
        return requested

    # auto
    if platform.machine() == "arm64" and platform.system() == "Darwin" and mlx_available():
        return "mlx"
    return "faster"


def transcribe_with_backend(
    audio_path,
    *,
    backend: str,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    beam_size: int = 1,
    language: Optional[str] = None,
) -> TranscriptionResult:
    if backend == "mlx":
        return _transcribe_mlx(audio_path, model_size, language=language)
    return _transcribe_faster(
        audio_path, model_size, device, compute_type, beam_size, language=language
    )


def _transcribe_mlx(
    audio_path,
    model_size: str,
    *,
    language: Optional[str] = None,
) -> TranscriptionResult:
    import mlx_whisper  # type: ignore

    repo = MLX_MODEL_REPOS.get(model_size, MLX_MODEL_REPOS["small"])
    lang_hint = f", language={language}" if language else ""
    print(f"    ⚡ mlx-whisper ({model_size}) on Apple Silicon{lang_hint}")

    audio, duration = load_audio_mono_16k(audio_path)
    decode_options = {"language": language} if language else {}
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=repo,
        verbose=False,
        word_timestamps=False,
        **decode_options,
    )

    segments = _segments_from_mlx(result.get("segments", []))
    return TranscriptionResult(
        segments=segments,
        language=result.get("language"),
        duration_seconds=duration,
        backend="mlx",
        model=repo,
    )


def _transcribe_faster(
    audio_path,
    model_size: str,
    device: str,
    compute_type: str,
    beam_size: int,
    *,
    language: Optional[str] = None,
) -> TranscriptionResult:
    from faster_whisper import WhisperModel  # type: ignore

    lang_hint = f", language={language}" if language else ""
    print(f"    🎙️  faster-whisper ({model_size}, {device}{lang_hint})")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    raw_segments, info = model.transcribe(
        str(audio_path),
        beam_size=beam_size,
        language=language,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments = [
        TranscriptSegment(
            start=float(seg.start),
            end=float(seg.end),
            text=seg.text.strip(),
        )
        for seg in raw_segments
        if seg.text.strip()
    ]

    return TranscriptionResult(
        segments=segments,
        language=info.language,
        duration_seconds=info.duration,
        backend="faster-whisper",
        model=model_size,
    )


def _segments_from_mlx(raw_segments: list) -> List[TranscriptSegment]:
    segments: List[TranscriptSegment] = []
    for seg in raw_segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=float(seg.get("start", 0)),
                end=float(seg.get("end", 0)),
                text=text,
            )
        )
    return segments