"""Tests for persisted session failures and retry."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import wave

from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import (
    archive_paths_for_failed_sessions,
    clear_session_failure,
    load_processed_log,
    record_session_failure,
    save_processed_log,
)
from ideaforge.pipeline import PipelineStages
from ideaforge.runner import process_source


def _write_wav(path: Path, *, seconds: float = 5.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12000
    samples = np.zeros(int(rate * seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_failure_persisted_then_cleared_on_success(tmp_path: Path):
    source = tmp_path / "device" / "RECORD"
    archive = tmp_path / "IdeaForge"
    source.mkdir(parents=True)

    stamp = datetime(2026, 6, 30, 8, 0, 0).strftime("R%Y-%m-%d-%H-%M-%S.WAV")
    wav = source / stamp
    _write_wav(wav)

    cfg = IdeaForgeConfig(archive=archive)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)

    def fail_once(audio_path, output_dir, **kwargs):
        stem = kwargs.get("output_stem", audio_path.stem)
        log = load_processed_log(archive)
        if stem not in log.get("failures", {}):
            raise RuntimeError("first attempt failed")
        transcript = output_dir / f"{stem}.txt"
        transcript.write_text("ok" * 30, encoding="utf-8")
        return transcript

    with patch("ideaforge.session_worker.transcribe_audio", side_effect=fail_once):
        first = process_source(
            source,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert first.files_processed == 0
    log = load_processed_log(archive)
    assert "R2026-06-30-08-00-00" in log["failures"]

    with patch("ideaforge.session_worker.transcribe_audio", side_effect=fail_once):
        second = process_source(
            source,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert second.files_processed == 1
    log = load_processed_log(archive)
    assert not log.get("failures")


def test_retry_failed_only_processes_logged_sessions(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    date_folder = archive / "2026-06-30"
    date_folder.mkdir(parents=True)
    wav = date_folder / "R2026-06-30-08-00-00.WAV"
    _write_wav(wav)

    log = load_processed_log(archive)
    record_session_failure(
        log,
        session_stem="R2026-06-30-08-00-00",
        archive_folder=date_folder,
        archive_files=[wav],
        chunk_hashes=["abc123"],
        error="boom",
        pipeline="copy → transcribe",
    )
    save_processed_log(archive, log)

    paths = archive_paths_for_failed_sessions(log)
    assert paths == [wav]

    cfg = IdeaForgeConfig(archive=archive)
    stages = PipelineStages(copy=False, transcribe=True, diarize=False, llm=False)

    with patch("ideaforge.session_worker.transcribe_audio") as transcribe:
        transcribe.return_value = date_folder / "R2026-06-30-08-00-00.txt"
        (date_folder / "R2026-06-30-08-00-00.txt").write_text("x" * 60, encoding="utf-8")
        result = process_source(
            archive,
            archive,
            cfg,
            stages,
            retry_failed_only=True,
            show_header=False,
            show_progress=False,
        )

    assert result.files_processed == 1
    transcribe.assert_called_once()
    assert not load_processed_log(archive).get("failures")


def test_clear_session_failure_removes_entry(tmp_path: Path):
    log = load_processed_log(tmp_path)
    record_session_failure(
        log,
        session_stem="R2026-06-30-08-00-00",
        archive_folder=tmp_path / "day",
        archive_files=[],
        chunk_hashes=[],
        error="x",
        pipeline="test",
    )
    clear_session_failure(log, "R2026-06-30-08-00-00")
    assert "R2026-06-30-08-00-00" not in log["failures"]