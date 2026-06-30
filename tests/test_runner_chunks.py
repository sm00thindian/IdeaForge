"""Integration tests for merged chunk processing."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import wave

from ideaforge.config import IdeaForgeConfig
from ideaforge.pipeline import PipelineStages
from ideaforge.runner import process_source


def _write_wav(path: Path, *, duration_seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12000
    samples = np.zeros(int(rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_process_source_merges_chunks_before_transcribe(tmp_path: Path):
    source = tmp_path / "device" / "RECORD"
    archive = tmp_path / "IdeaForge"
    source.mkdir(parents=True)

    base = datetime(2025, 7, 7, 17, 0, 0)
    for offset_seconds in (0, 15 * 60 + 5):
        stamp = base + timedelta(seconds=offset_seconds)
        name = stamp.strftime("R%Y-%m-%d-%H-%M-%S.WAV")
        _write_wav(source / name, duration_seconds=15 * 60)

    cfg = IdeaForgeConfig(
        archive=archive,
        merge_chunks=True,
        chunk_gap_seconds=30,
        merge_min_chunk_seconds=600,
    )
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)

    with patch("ideaforge.session_worker.transcribe_audio") as transcribe:
        transcribe.return_value = archive / "2025-07-07" / "R2025-07-07-17-00-00.txt"
        result = process_source(
            source,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert result.files_processed == 1
    transcribe.assert_called_once()
    audio_arg = transcribe.call_args.args[0]
    assert audio_arg.name == "R2025-07-07-17-00-00_merged.WAV"
    assert transcribe.call_args.kwargs["output_stem"] == "R2025-07-07-17-00-00"