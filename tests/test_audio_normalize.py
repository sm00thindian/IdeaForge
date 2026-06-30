"""Tests for ffmpeg audio normalization helpers."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.audio_util import (
    ensure_pipeline_audio,
    needs_audio_normalization,
    normalize_to_wav,
)


def test_needs_audio_normalization_detects_mp3(tmp_path: Path):
    path = tmp_path / "clip.mp3"
    path.write_bytes(b"fake")
    assert needs_audio_normalization(path)


def test_needs_audio_normalization_pcm_wav(tmp_path: Path):
    import wave

    path = tmp_path / "clip.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1000)
    assert not needs_audio_normalization(path)


@patch("ideaforge.audio_util._run_command")
def test_normalize_to_wav_invokes_ffmpeg(mock_run, tmp_path: Path):
    source = tmp_path / "clip.flac"
    source.write_bytes(b"fake")
    with patch("ideaforge.audio_util.ffmpeg_available", return_value=True):
        output = normalize_to_wav(source, tmp_path / "out")
    assert output.name == "clip_normalized.wav"
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0][0] == "ffmpeg"


def test_ensure_pipeline_audio_skips_when_disabled(tmp_path: Path):
    import wave

    path = tmp_path / "clip.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1000)
    result = ensure_pipeline_audio(path, tmp_path, normalize_audio=False)
    assert result == path


@patch("ideaforge.audio_util.normalize_to_wav")
def test_ensure_pipeline_audio_normalizes_mp3(mock_normalize, tmp_path: Path):
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"fake")
    mock_normalize.return_value = tmp_path / "clip_normalized.wav"
    result = ensure_pipeline_audio(source, tmp_path, normalize_audio=True)
    assert result == tmp_path / "clip_normalized.wav"
    mock_normalize.assert_called_once_with(source, tmp_path)


