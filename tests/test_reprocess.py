"""Tests for ideaforge --reprocess."""

import argparse
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import wave

from ideaforge.config import IdeaForgeConfig
from ideaforge.reprocess import (
    collect_reprocess_scope,
    resolve_reprocess_folders,
    run_reprocess,
)


def _write_wav(path: Path, *, seconds: float = 5.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12000
    samples = np.zeros(int(rate * seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def _archive_layout(tmp_path: Path) -> Path:
    archive = tmp_path / "IdeaForge"
    for day in ("2026-06-27", "2026-06-28", "2026-06-29"):
        folder = archive / day
        stamp = datetime.strptime(day, "%Y-%m-%d").strftime("R%Y-%m-%d-08-00-00.WAV")
        _write_wav(folder / stamp)
    return archive


def test_resolve_reprocess_folders_single_date(tmp_path: Path):
    archive = _archive_layout(tmp_path)
    folders = resolve_reprocess_folders(archive, archive / "2026-06-28")
    assert [f.name for f in folders] == ["2026-06-28"]


def test_resolve_reprocess_folders_date_range(tmp_path: Path):
    archive = _archive_layout(tmp_path)
    folders = resolve_reprocess_folders(
        archive,
        archive,
        date_from="2026-06-27",
        date_to="2026-06-28",
    )
    assert [f.name for f in folders] == ["2026-06-27", "2026-06-28"]


def test_collect_reprocess_scope_filters_session_stem(tmp_path: Path):
    archive = _archive_layout(tmp_path)
    cfg = IdeaForgeConfig(archive=archive)
    scope = collect_reprocess_scope(
        archive,
        archive,
        cfg,
        session_stems=["R2026-06-28-08-00-00"],
    )
    assert len(scope) == 1
    assert scope[0].parent.name == "2026-06-28"


def test_run_reprocess_invokes_pipeline_with_force(tmp_path: Path):
    archive = _archive_layout(tmp_path)
    cfg = IdeaForgeConfig(archive=archive)
    args = argparse.Namespace(
        source=archive / "2026-06-27",
        reprocess_from=None,
        reprocess_to=None,
        reprocess_sessions=None,
        llm_only=False,
        diarize_only=False,
        transcribe_only=False,
        no_copy=False,
        no_transcribe=False,
        no_llm=False,
        force=False,
    )

    with patch("ideaforge.reprocess.process_source") as process:
        assert run_reprocess(cfg, args) == 0

    process.assert_called_once()
    kwargs = process.call_args.kwargs
    assert kwargs["force"] is True
    assert kwargs["include_failed_retries"] is False
    assert len(kwargs["scope_files"]) == 1