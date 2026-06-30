"""Tests for audio loading."""

import wave
from pathlib import Path

import numpy as np

from ideaforge.audio_util import (
    concat_wav_files,
    get_audio_duration_seconds,
    load_audio_mono_16k,
)


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


def test_concat_wav_files(tmp_path: Path):
    paths = []
    for index in range(3):
        path = tmp_path / f"part{index}.wav"
        rate = 12000
        duration = 1
        t = np.linspace(0, duration, rate * duration, endpoint=False)
        audio = (0.25 * np.sin(2 * np.pi * 220 * (index + 1) * t) * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(audio.tobytes())
        paths.append(path)

    merged = concat_wav_files(paths, tmp_path / "merged.wav")
    assert merged.exists()
    assert get_audio_duration_seconds(merged) == 3.0


def test_concat_wav_files_same_format_different_lengths(tmp_path: Path):
    """Chunks from one session can differ in length but share format."""
    paths = []
    for duration in (2, 15):
        path = tmp_path / f"chunk_{duration}s.wav"
        rate = 16000
        t = np.linspace(0, duration, rate * duration, endpoint=False)
        audio = (0.25 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(audio.tobytes())
        paths.append(path)

    merged = concat_wav_files(paths, tmp_path / "merged.wav")
    assert get_audio_duration_seconds(merged) == 17.0