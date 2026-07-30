"""Tests for post-success merged WAV → MP3 compression."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import wave

from ideaforge.audio_util import compress_merged_wav_to_mp3, encode_wav_to_mp3
from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import iter_merged_audio_files, prune_old_merged_wavs
from datetime import datetime, timedelta
import os


def _write_wav(path: Path, *, duration_seconds: float = 0.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12_000
    samples = np.zeros(int(rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_config_merge_to_mp3_defaults():
    cfg = IdeaForgeConfig()
    assert cfg.merge_to_mp3 is True
    assert cfg.merge_mp3_bitrate == "64k"


def test_config_loads_merge_to_mp3(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[processing]
merge_to_mp3 = false
merge_mp3_bitrate = "96k"
""".strip(),
        encoding="utf-8",
    )
    cfg = IdeaForgeConfig.from_toml(config)
    assert cfg.merge_to_mp3 is False
    assert cfg.merge_mp3_bitrate == "96k"


def test_compress_merged_wav_to_mp3(tmp_path: Path):
    wav = tmp_path / "R2026-07-22-09-00-00_merged.wav"
    _write_wav(wav, duration_seconds=1.0)

    def fake_encode(wav_path: Path, output=None, *, bitrate: str = "64k") -> Path:
        dest = output or wav_path.with_suffix(".mp3")
        dest.write_bytes(b"ID3fake-mp3")
        return dest

    with patch("ideaforge.audio_util.encode_wav_to_mp3", side_effect=fake_encode):
        mp3 = compress_merged_wav_to_mp3(wav, bitrate="64k", delete_wav=True)

    assert mp3.name == "R2026-07-22-09-00-00_merged.mp3"
    assert mp3.is_file()
    assert not wav.exists()


def test_prune_finds_merged_mp3(tmp_path: Path):
    now = datetime(2026, 7, 22, 3, 0, 0)
    session = tmp_path / "2026-07-10" / "R2026-07-10-09-00-00"
    session.mkdir(parents=True)
    mp3 = session / "R2026-07-10-09-00-00_merged.mp3"
    mp3.write_bytes(b"\x00" * 2048)
    old = (now - timedelta(days=5)).timestamp()
    os.utime(mp3, (old, old))

    found = iter_merged_audio_files(tmp_path)
    assert mp3 in found

    removed = prune_old_merged_wavs(tmp_path, retain_days=3, now=now)
    assert removed == [mp3]
    assert not mp3.exists()


def test_compress_rejects_non_merged_name(tmp_path: Path):
    wav = tmp_path / "R2026-07-22-09-00-00.WAV"
    _write_wav(wav)
    try:
        compress_merged_wav_to_mp3(wav)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "not a merged artifact" in str(exc)
