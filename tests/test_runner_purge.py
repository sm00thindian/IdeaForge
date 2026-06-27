"""Tests for device purge after archive copy."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.pipeline import PipelineStages
from ideaforge.runner import process_source


def _recorder_layout(tmp_path: Path) -> tuple[Path, Path]:
    volume = tmp_path / "Volumes" / "RECORDER"
    record = volume / "RECORD"
    record.mkdir(parents=True)
    archive = tmp_path / "IdeaForge"
    return volume, archive


def test_daemon_purge_removes_file_after_copy(tmp_path: Path):
    volume, archive = _recorder_layout(tmp_path)
    wav = volume / "RECORD" / "R2026-06-27-07-43-11.WAV"
    wav.write_bytes(b"\x00" * 60_000)

    cfg = IdeaForgeConfig()
    cfg.archive = archive
    stages = PipelineStages(copy=True, transcribe=False, diarize=False, llm=False)

    with patch("ideaforge.runner.is_path_on_recorder", return_value=True):
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
    assert (archive / "2026-06-27" / wav.name).exists()


def test_manual_run_keeps_device_files_by_default(tmp_path: Path):
    volume, archive = _recorder_layout(tmp_path)
    wav = volume / "RECORD" / "R2026-06-27-07-43-11.WAV"
    wav.write_bytes(b"\x00" * 60_000)

    cfg = IdeaForgeConfig()
    cfg.archive = archive
    stages = PipelineStages(copy=True, transcribe=False, diarize=False, llm=False)

    with patch("ideaforge.runner.is_path_on_recorder", return_value=True):
        process_source(
            volume,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert wav.exists()