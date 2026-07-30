"""Tests for device purge after archive copy."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.ingest import archive_folder_for_file
from ideaforge.pipeline import PipelineStages
from ideaforge.runner import process_source


def _recorder_layout(tmp_path: Path) -> tuple[Path, Path]:
    volume = tmp_path / "Volumes" / "RECORDER"
    record = volume / "RECORD"
    record.mkdir(parents=True)
    archive = tmp_path / "IdeaForge"
    return volume, archive


def _write_minimal_wav(path: Path, *, nbytes: int = 60_000) -> None:
    """Valid RIFF WAV large enough to pass min_file_size_bytes."""
    import numpy as np
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    n = max(rate, nbytes // 2)
    samples = np.zeros(n, dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def test_daemon_purge_removes_file_after_copy(tmp_path: Path):
    volume, archive = _recorder_layout(tmp_path)
    wav = volume / "RECORD" / "R2026-06-27-07-43-11.WAV"
    _write_minimal_wav(wav)
    date_folder = archive_folder_for_file(wav, archive).name

    cfg = IdeaForgeConfig(archive=archive, merge_to_mp3=False)
    stages = PipelineStages(copy=True, transcribe=False, diarize=False, llm=False)

    with patch("ideaforge.session_worker.is_path_on_recorder", return_value=True):
        result = process_source(
            volume,
            archive,
            cfg,
            stages,
            delete_from_device=True,
            show_header=False,
            show_progress=False,
        )

    assert result.files_processed == 1
    assert not wav.exists()
    session_dir = archive / date_folder / wav.stem
    assert (session_dir / wav.name).exists()


def test_manual_run_keeps_device_files_by_default(tmp_path: Path):
    volume, archive = _recorder_layout(tmp_path)
    wav = volume / "RECORD" / "R2026-06-27-07-43-11.WAV"
    _write_minimal_wav(wav)

    cfg = IdeaForgeConfig(archive=archive, merge_to_mp3=False)
    stages = PipelineStages(copy=True, transcribe=False, diarize=False, llm=False)

    with patch("ideaforge.session_worker.is_path_on_recorder", return_value=True):
        process_source(
            volume,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert wav.exists()