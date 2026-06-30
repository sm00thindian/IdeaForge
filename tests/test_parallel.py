"""Tests for parallel session processing."""

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import wave

from ideaforge.config import IdeaForgeConfig
from ideaforge.gpu_lock import gpu_stage
from ideaforge.pipeline import PipelineStages
from ideaforge.runner import process_source


def _write_wav(path: Path, *, duration_seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12000
    samples = np.zeros(int(rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_gpu_stage_serializes_threads():
    state = {"active": 0, "max": 0}

    def worker() -> None:
        with gpu_stage():
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            time.sleep(0.05)
            state["active"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert state["max"] == 1


def test_process_source_parallel_sessions(tmp_path: Path):
    source = tmp_path / "device" / "RECORD"
    archive = tmp_path / "IdeaForge"
    source.mkdir(parents=True)

    base = datetime(2026, 6, 30, 8, 0, 0)
    for offset_minutes in (0, 30):
        stamp = (base + timedelta(minutes=offset_minutes)).strftime("R%Y-%m-%d-%H-%M-%S.WAV")
        _write_wav(source / stamp, duration_seconds=60)

    cfg = IdeaForgeConfig(archive=archive, max_parallel_sessions=2)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=True)
    call_order: list[str] = []

    def fake_transcribe(audio_path, output_dir, **kwargs):
        call_order.append(f"gpu-start:{audio_path.stem}")
        time.sleep(0.05)
        call_order.append(f"gpu-end:{audio_path.stem}")
        transcript = output_dir / f"{kwargs.get('output_stem', audio_path.stem)}.txt"
        transcript.write_text("x" * 60, encoding="utf-8")
        return transcript

    def fake_llm(transcript_path, output_dir, **kwargs):
        call_order.append(f"llm:{transcript_path.stem}")
        (output_dir / f"{transcript_path.stem}_summary.json").write_text("{}", encoding="utf-8")
        (output_dir / f"{transcript_path.stem}_summary.md").write_text("# test", encoding="utf-8")
        return output_dir / f"{transcript_path.stem}_summary.md"

    with (
        patch("ideaforge.session_worker.transcribe_audio", side_effect=fake_transcribe),
        patch("ideaforge.session_worker.process_transcript", side_effect=fake_llm),
    ):
        result = process_source(
            source,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert result.files_processed == 2
    assert sum(1 for item in call_order if item.startswith("gpu-start:")) == 2
    assert any(item.startswith("llm:") for item in call_order)