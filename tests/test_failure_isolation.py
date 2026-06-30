"""Tests for per-session failure isolation."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import wave

from ideaforge.config import IdeaForgeConfig
from ideaforge.pipeline import PipelineStages
from ideaforge.runner import process_source


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12000
    samples = np.zeros(rate * 5, dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_one_failed_session_does_not_block_others(tmp_path: Path):
    source = tmp_path / "device" / "RECORD"
    archive = tmp_path / "IdeaForge"
    source.mkdir(parents=True)

    base = datetime(2026, 6, 30, 8, 0, 0)
    names = []
    for offset_minutes in (0, 30):
        stamp = (base + timedelta(minutes=offset_minutes)).strftime("R%Y-%m-%d-%H-%M-%S.WAV")
        path = source / stamp
        _write_wav(path)
        names.append(path.stem)

    cfg = IdeaForgeConfig(archive=archive, max_parallel_sessions=1)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)
    calls: list[str] = []

    def fake_transcribe(audio_path, output_dir, **kwargs):
        stem = kwargs.get("output_stem", audio_path.stem)
        calls.append(stem)
        if stem == names[0]:
            raise RuntimeError("simulated transcribe failure")
        transcript = output_dir / f"{stem}.txt"
        transcript.write_text("ok" * 30, encoding="utf-8")
        return transcript

    with patch("ideaforge.session_worker.transcribe_audio", side_effect=fake_transcribe):
        result = process_source(
            source,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert result.files_processed == 1
    assert any(rec.failed for rec in result.recordings)
    assert names[1] in calls