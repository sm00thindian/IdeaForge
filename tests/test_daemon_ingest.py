"""Tests for daemon ingest-first + unmount workflow."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.daemon import RecorderWatcher, daemon_process_device
from ideaforge.device import RecorderDevice
from ideaforge.ingest import IngestResult
from ideaforge.notify import ProcessResult
from ideaforge.pipeline import PipelineStages


def _device(tmp_path: Path) -> RecorderDevice:
    mount = tmp_path / "NO NAME"
    record = mount / "RECORD"
    record.mkdir(parents=True)
    wav = record / "R2026-06-27-07-43-11.WAV"
    wav.write_bytes(b"\x00" * 60_000)
    return RecorderDevice(
        mount_path=mount,
        record_folder=record,
        settings_file=None,
        recording_count=1,
    )


def test_daemon_process_device_ingests_then_processes_archive(tmp_path: Path):
    device = _device(tmp_path)
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)

    archive_copy = archive / "2026-06-27" / "R2026-06-27-07-43-11.WAV"
    ingest = IngestResult(archive_files=[archive_copy], files_verified=1, files_deleted=1)

    with (
        patch("ideaforge.daemon.ingest_device_recordings", return_value=ingest),
        patch("ideaforge.daemon.get_audio_files", return_value=[]),
        patch("ideaforge.daemon.unmount_volume", return_value=True) as unmount,
        patch("ideaforge.daemon.process_source", return_value=ProcessResult(files_processed=1)) as process,
    ):
        result = daemon_process_device(
            device.mount_path,
            archive,
            cfg,
            stages,
        )

    assert result.files_processed == 1
    unmount.assert_called_once_with(device.mount_path)
    process.assert_called_once()
    call_kwargs = process.call_args.kwargs
    stages_arg = process.call_args[0][3]
    assert call_kwargs["scope_files"] == ingest.archive_files
    assert call_kwargs["delete_from_device"] is False
    assert stages_arg.copy is False


def test_daemon_process_device_skips_unmount_on_ingest_failure(tmp_path: Path):
    device = _device(tmp_path)
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive)
    stages = PipelineStages(copy=True, transcribe=False, diarize=False, llm=False)

    ingest = IngestResult(files_failed=1)

    with (
        patch("ideaforge.daemon.ingest_device_recordings", return_value=ingest),
        patch("ideaforge.daemon.unmount_volume") as unmount,
        patch("ideaforge.daemon.process_source") as process,
    ):
        result = daemon_process_device(device.mount_path, archive, cfg, stages)

    assert result.files_processed == 0
    unmount.assert_not_called()
    process.assert_not_called()


def test_watcher_uses_daemon_process_fn_by_default():
    watcher = RecorderWatcher(
        cfg=IdeaForgeConfig(),
        stages=PipelineStages(copy=True, transcribe=True, diarize=False, llm=True),
        sleep_fn=lambda _s: None,
    )
    assert watcher.process_fn.__name__ == "daemon_process_device"