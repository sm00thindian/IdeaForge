"""Tests for age-based pruning of leftover merged WAV artifacts."""

import os
from datetime import datetime, timedelta
from pathlib import Path

from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import iter_merged_wav_files, prune_old_merged_wavs


def _touch_merged(path: Path, *, mtime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 1024)
    os.utime(path, (mtime, mtime))
    return path


def test_iter_merged_wav_files_finds_case_variants(tmp_path: Path):
    day = tmp_path / "2026-07-01"
    _touch_merged(day / "R2026-07-01-09-00-00_merged.wav", mtime=1.0)
    _touch_merged(day / "R2026-07-01-10-00-00_merged.WAV", mtime=1.0)
    (day / "R2026-07-01-09-00-00.WAV").write_bytes(b"\x00" * 100)

    found = {p.name for p in iter_merged_wav_files(tmp_path)}
    assert found == {
        "R2026-07-01-09-00-00_merged.wav",
        "R2026-07-01-10-00-00_merged.WAV",
    }


def test_prune_old_merged_wavs_removes_only_old_files(tmp_path: Path):
    now = datetime(2026, 7, 10, 3, 0, 0)
    old_mtime = (now - timedelta(days=5)).timestamp()
    fresh_mtime = (now - timedelta(days=1)).timestamp()

    old = _touch_merged(
        tmp_path / "2026-07-05" / "R2026-07-05-09-00-00_merged.wav",
        mtime=old_mtime,
    )
    fresh = _touch_merged(
        tmp_path / "2026-07-09" / "R2026-07-09-09-00-00_merged.wav",
        mtime=fresh_mtime,
    )
    source = tmp_path / "2026-07-05" / "R2026-07-05-09-00-00.WAV"
    source.write_bytes(b"\x00" * 100)
    os.utime(source, (old_mtime, old_mtime))

    removed = prune_old_merged_wavs(tmp_path, retain_days=3, now=now)

    assert removed == [old]
    assert not old.exists()
    assert fresh.is_file()
    assert source.is_file()


def test_prune_old_merged_wavs_disabled_when_zero(tmp_path: Path):
    now = datetime(2026, 7, 10, 3, 0, 0)
    old = _touch_merged(
        tmp_path / "R2026-07-01-09-00-00_merged.wav",
        mtime=(now - timedelta(days=30)).timestamp(),
    )

    assert prune_old_merged_wavs(tmp_path, retain_days=0, now=now) == []
    assert old.is_file()


def test_prune_old_merged_wavs_missing_archive(tmp_path: Path):
    missing = tmp_path / "nope"
    assert prune_old_merged_wavs(missing, retain_days=3) == []


def test_config_loads_merged_wav_retain_days(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[daemon]
merged_wav_retain_days = 7
""".strip(),
        encoding="utf-8",
    )
    cfg = IdeaForgeConfig.from_toml(config)
    assert cfg.daemon_merged_wav_retain_days == 7


def test_config_default_merged_wav_retain_days():
    assert IdeaForgeConfig().daemon_merged_wav_retain_days == 3
