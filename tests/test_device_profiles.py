"""Tests for device profile adapters."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import wave

from ideaforge.device_profiles import GenericWavProfile, Z28Profile, get_profile, mount_matches_glob


def _write_wav(path: Path, *, duration_seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12_000
    samples = np.zeros(int(rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_mount_matches_glob():
    assert mount_matches_glob("NO NAME", "NO NAME")
    assert mount_matches_glob("RECORDER", "REC*")
    assert not mount_matches_glob("Other", "NO NAME")


def test_z28_profile_discovers_record_folder_files(tmp_path: Path):
    mount = tmp_path / "NO NAME"
    record = mount / "RECORD"
    record.mkdir(parents=True)
    wav = record / "R2026-06-30-09-00-00.WAV"
    _write_wav(wav, duration_seconds=5.0)

    profile = Z28Profile()
    assert profile.matches_mount(mount)
    files = profile.discover_files(mount, {".wav", ".WAV"}, min_size_bytes=1_000)
    assert files == [wav]
    assert profile.parse_session_id(wav) == "R2026-06-30-09-00-00"


def test_generic_wav_profile_recursive_discovery(tmp_path: Path):
    mount = tmp_path / "RECORDER"
    nested = mount / "audio" / "meetings"
    nested.mkdir(parents=True)
    wav = nested / "team-sync.wav"
    _write_wav(wav, duration_seconds=5.0)

    profile = GenericWavProfile()
    assert profile.matches_mount(mount)
    files = profile.discover_files(mount, {".wav"}, min_size_bytes=1_000)
    assert files == [wav]
    assert profile.settings_file(mount) is None


def test_get_profile_unknown_raises():
    try:
        get_profile("unknown-vendor")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unknown" in str(exc).lower()