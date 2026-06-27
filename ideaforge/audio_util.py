"""Audio loading utilities — ffmpeg-free fallback for mlx-whisper."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Tuple

import numpy as np

TARGET_SAMPLE_RATE = 16_000


def get_audio_duration_seconds(path: Path) -> float:
    """Return duration in seconds using the wave module (WAV/PCM)."""
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def load_audio_mono_16k(path: Path) -> Tuple[np.ndarray, float]:
    """
    Load audio as float32 mono @ 16 kHz without ffmpeg.
    Supports PCM WAV files (including Z28/Z29 recorder output).
    """
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sample_width} bytes")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    duration = len(audio) / sample_rate

    if sample_rate != TARGET_SAMPLE_RATE:
        audio = _resample(audio, sample_rate, TARGET_SAMPLE_RATE)
        duration = len(audio) / TARGET_SAMPLE_RATE

    return audio, duration


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    try:
        from scipy.signal import resample_poly  # type: ignore

        g = _gcd(src_rate, dst_rate)
        return resample_poly(audio, dst_rate // g, src_rate // g).astype(np.float32)
    except ImportError:
        # Nearest-neighbor fallback
        duration = len(audio) / src_rate
        dst_length = int(duration * dst_rate)
        indices = np.linspace(0, len(audio) - 1, dst_length).astype(int)
        return audio[indices].astype(np.float32)


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a