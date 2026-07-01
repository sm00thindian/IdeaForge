"""Tests for daemon ingest-first + unmount workflow."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.daemon import RecorderWatcher, daemon_process_device
from ideaforge.device import RecorderDevice
from ideaforge.ingest import IngestResult
from ideaforge.notify import ProcessResult
from ideaforge.pipeline import PipelineStages
from ideaforge.status import StatusReporter


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
        patch("ideaforge.daemon.run_device_ingest", return_value=ingest),
        patch("ideaforge.daemon.load_processed_log", return_value={"failures": {}}),
        patch("ideaforge.daemon.process_source", return_value=ProcessResult(files_processed=1)) as process,
    ):
        result = daemon_process_device(
            device.mount_path,
            archive,
            cfg,
            stages,
        )

    assert result.files_processed == 1
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
        patch("ideaforge.daemon.run_device_ingest", return_value=ingest),
        patch("ideaforge.daemon.load_processed_log", return_value={"failures": {}}),
        patch("ideaforge.daemon.process_source") as process,
    ):
        result = daemon_process_device(device.mount_path, archive, cfg, stages)

    assert result.files_processed == 0
    process.assert_not_called()


def test_daemon_process_device_retries_failures_without_new_ingest(tmp_path: Path):
    device = _device(tmp_path)
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)
    empty_ingest = IngestResult()

    with (
        patch("ideaforge.daemon.run_device_ingest", return_value=empty_ingest),
        patch(
            "ideaforge.daemon.load_processed_log",
            return_value={"failures": {"R2026-06-27-07-43-11": {}}},
        ),
        patch("ideaforge.daemon.process_source", return_value=ProcessResult(files_processed=1)) as process,
    ):
        result = daemon_process_device(device.mount_path, archive, cfg, stages)

    assert result.files_processed == 1
    process.assert_called_once()
    assert process.call_args.kwargs["scope_files"] is None


def test_daemon_process_device_passes_reporter_to_process_source(tmp_path: Path):
    device = _device(tmp_path)
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)
    reporter = StatusReporter(enabled=False)
    archive_copy = archive / "2026-06-27" / "R2026-06-27-07-43-11.WAV"
    ingest = IngestResult(archive_files=[archive_copy], files_verified=1)

    with (
        patch("ideaforge.daemon.run_device_ingest", return_value=ingest),
        patch("ideaforge.daemon.load_processed_log", return_value={"failures": {}}),
        patch("ideaforge.daemon.process_source", return_value=ProcessResult(files_processed=1)) as process,
    ):
        daemon_process_device(
            device.mount_path,
            archive,
            cfg,
            stages,
            reporter=reporter,
        )

    assert process.call_args.kwargs["reporter"] is reporter
    assert process.call_args.kwargs["device_label"] == device.mount_path.name


def test_daemon_process_device_skips_clock_sync_during_ingest(tmp_path: Path):
    device = _device(tmp_path)
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(archive=archive)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)
    ingest = IngestResult()

    with (
        patch("ideaforge.daemon.run_device_ingest", return_value=ingest) as run_ingest,
        patch("ideaforge.daemon.load_processed_log", return_value={"failures": {}}),
    ):
        daemon_process_device(device.mount_path, archive, cfg, stages)

    assert run_ingest.call_args.kwargs.get("sync_clock") is False


def test_watcher_uses_daemon_process_fn_by_default():
    watcher = RecorderWatcher(
        cfg=IdeaForgeConfig(),
        stages=PipelineStages(copy=True, transcribe=True, diarize=False, llm=True),
        sleep_fn=lambda _s: None,
    )
    assert watcher.process_fn.__name__ == "daemon_process_device"