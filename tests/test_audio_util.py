"""Tests for audio loading."""

import wave
from pathlib import Path

import numpy as np

from ideaforge.audio_util import get_audio_duration_seconds, load_audio_mono_16k


def test_load_and_resample_mono_wav(tmp_path: Path):
    path = tmp_path / "test.wav"
    rate = 12000
    duration = 2
    t = np.linspace(0, duration, rate * duration, endpoint=False)
    audio = (0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio.tobytes())

    loaded, dur = load_audio_mono_16k(path)
    assert len(loaded) == 16000 * duration
    assert abs(dur - duration) < 0.1
    assert get_audio_duration_seconds(path) == duration