"""USB recorder watcher daemon — auto-process when device is plugged in."""

from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from ideaforge.config import IdeaForgeConfig
from ideaforge.device import RecorderDevice, find_recorder_mounts, unmount_volume
from ideaforge.ingest import (
    IngestResult,
    get_audio_files,
    ingest_device_recordings,
    load_processed_log,
)
from ideaforge.pipeline import PipelineStages, resolve_stages
from ideaforge.notify import ProcessResult, notify_process_complete
from ideaforge.runner import process_source
from ideaforge.status import StatusReporter


@dataclass(frozen=True)
class DeviceSnapshot:
    """Fingerprint of recorder contents — used to skip redundant pipeline runs."""

    mount_path: str
    recording_count: int
    newest_mtime: float

    @classmethod
    def from_device(cls, device: RecorderDevice) -> "DeviceSnapshot":
        newest = 0.0
        folder = device.record_folder
        if folder.is_dir():
            for pattern in ("R*.WAV", "R*.wav"):
                for wav in folder.glob(pattern):
                    try:
                        newest = max(newest, wav.stat().st_mtime)
                    except OSError:
                        pass
        return cls(
            mount_path=str(device.mount_path),
            recording_count=device.recording_count,
            newest_mtime=newest,
        )


def snapshot_device(device: RecorderDevice) -> DeviceSnapshot:
    return DeviceSnapshot.from_device(device)


def maybe_unmount_device(
    source: Path,
    cfg: IdeaForgeConfig,
    ingest: IngestResult,
) -> bool:
    """Unmount recorder volume when ingest succeeded and RECORD/ is empty."""
    if not cfg.daemon_unmount_after_ingest or not ingest.device_cleared:
        return False
    extensions = set(cfg.audio_extensions)
    remaining = get_audio_files(source, extensions, cfg.min_file_size_bytes)
    if remaining:
        return False
    label = source.name
    if unmount_volume(source):
        print(f"   📴 Unmounted {label}")
        return True
    print(f"   ⚠️  Could not unmount {label}")
    return False


def run_device_ingest(
    source: Path,
    archive: Path,
    cfg: IdeaForgeConfig,
    *,
    delete_after_copy: Optional[bool] = None,
    unmount_after: Optional[bool] = None,
    reporter: Optional[StatusReporter] = None,
) -> IngestResult:
    """Copy device recordings to archive, verify, optionally purge and unmount."""
    delete = (
        cfg.daemon_delete_after_copy
        if delete_after_copy is None
        else delete_after_copy
    )
    ingest = ingest_device_recordings(
        source,
        archive,
        cfg,
        delete_after_copy=delete,
        reporter=reporter,
    )

    if ingest.files_failed:
        print("   ⚠️  Ingest incomplete — device will stay mounted")
    elif unmount_after is not False:
        maybe_unmount_device(source, cfg, ingest)

    return ingest


def daemon_process_device(
    source: Path,
    archive: Path,
    cfg: IdeaForgeConfig,
    stages: PipelineStages,
    *,
    force: bool = False,
    export_settings=None,
    reporter: Optional[StatusReporter] = None,
    **_kwargs,
) -> ProcessResult:
    """
    Daemon pipeline: ingest device files locally first (copy → verify → purge),
    optionally unmount, then transcribe/diarize/summarize from archive only.
    """
    ingest = run_device_ingest(source, archive, cfg, reporter=reporter)

    processed_log = load_processed_log(archive)
    has_failures = bool(processed_log.get("failures"))
    if not ingest.has_work and not has_failures:
        return ProcessResult()

    scope = ingest.archive_files if ingest.has_work else None
    return process_source(
        archive,
        archive,
        cfg,
        stages.without_copy(),
        force=force,
        delete_from_device=False,
        export_settings=export_settings,
        scope_files=scope,
        include_failed_retries=True,
    )


class RecorderWatcher:
    """Poll /Volumes for USB recorders and trigger the pipeline on connect or new files."""

    def __init__(
        self,
        *,
        cfg: IdeaForgeConfig,
        stages: PipelineStages,
        poll_interval: float = 5.0,
        settle_seconds: float = 5.0,
        force: bool = False,
        sleep_fn: Callable[[float], None] = time.sleep,
        process_fn: Callable[..., ProcessResult] = daemon_process_device,
    ) -> None:
        self.cfg = cfg
        self.stages = stages
        self.poll_interval = poll_interval
        self.settle_seconds = settle_seconds
        self.force = force
        self.sleep_fn = sleep_fn
        self.process_fn = process_fn

        self._connected: Set[str] = set()
        self._settled: Set[str] = set()
        self._last_snapshot: Dict[str, DeviceSnapshot] = {}
        self._running = True
        self._status = StatusReporter()

    def stop(self) -> None:
        self._running = False

    def tick(self) -> Optional[ProcessResult]:
        """Single poll cycle. Returns pipeline result, or None if idle."""
        devices = find_recorder_mounts()
        current = {str(device.mount_path): device for device in devices}
        current_mounts = set(current.keys())

        for mount in sorted(self._connected - current_mounts):
            label = Path(mount).name
            print(f"📴 Recorder disconnected: {label}")
            self._settled.discard(mount)
        self._connected = current_mounts

        if not current:
            self._status.set_watching()
            return None

        if len(current) > 1:
            names = ", ".join(Path(m).name for m in sorted(current))
            print(f"⚠️  Multiple recorders detected ({names}) — unplug extras")
            self._status.set_idle(detail="Multiple recorders detected — unplug extras")
            return None

        device = next(iter(current.values()))
        mount_key = str(device.mount_path)

        if mount_key not in self._settled:
            print(
                f"📼 Recorder connected: {device.label} "
                f"({device.recording_count} recording(s))"
            )
            self._status.set_settling(
                device=device.label,
                recording_count=device.recording_count,
            )
            if self.settle_seconds > 0:
                print(f"   Waiting {self.settle_seconds:.0f}s for mount to settle...")
                self.sleep_fn(self.settle_seconds)
            refreshed = find_recorder_mounts()
            if len(refreshed) == 1:
                device = refreshed[0]
                mount_key = str(device.mount_path)
            self._settled.add(mount_key)

        snap = snapshot_device(device)
        if self._last_snapshot.get(mount_key) == snap and not self.force:
            print(f"   No new recordings on {device.label} — skipping")
            self._status.set_watching(device=device.label)
            return None

        archive = self.cfg.archive.expanduser().resolve()
        pipeline_result = self.process_fn(
            device.mount_path,
            archive,
            self.cfg,
            self.stages,
            force=self.force,
            export_settings=self.cfg.export_settings(force=self.force),
            reporter=self._status,
        )
        if self.cfg.daemon_notify and (
            pipeline_result.files_processed > 0 or pipeline_result.files_skipped > 0
        ):
            notify_process_complete(pipeline_result, device_label=device.label)
        refreshed = find_recorder_mounts()
        if len(refreshed) == 1:
            self._last_snapshot[mount_key] = snapshot_device(refreshed[0])
        else:
            self._last_snapshot[mount_key] = snap
        return pipeline_result

    def run(self) -> int:
        from ideaforge import __version__

        print(f"👀 IdeaForge daemon v{__version__}")
        print(f"   Watching /Volumes every {self.poll_interval:.0f}s")
        print(f"   Archive: {self.cfg.archive.expanduser()}")
        print(f"   Pipeline: {self.stages.label}")
        resolved_llm = self.cfg.resolve_llm_backend()
        print(f"   LLM: {resolved_llm} ({self.cfg.llm_backend} in config)")
        if resolved_llm == "ollama" and self.cfg.llm_backend in ("auto", "grok"):
            print(
                "   ⚠️  XAI_API_KEY not found — export it and run "
                "./scripts/install-daemon.sh, or add to .env"
            )
        print("   Press Ctrl+C to stop\n")
        self._status.set_watching()

        while self._running:
            try:
                self.tick()
            except Exception as exc:
                print(f"❌ Daemon error: {exc}", file=sys.stderr)
            self.sleep_fn(self.poll_interval)
        return 0


def run_daemon(
    cfg: IdeaForgeConfig,
    args,
    *,
    poll_interval: Optional[float] = None,
    settle_seconds: Optional[float] = None,
    config_path: Optional[Path] = None,
) -> int:
    """Run the recorder watcher until SIGINT/SIGTERM."""
    from ideaforge.config_validate import ConfigValidationError, validate_config_file

    path = config_path or cfg.default_config_path()
    if path.is_file():
        try:
            validate_config_file(path)
        except ConfigValidationError as exc:
            print(f"❌ Invalid config ({path}):\n{exc}", file=sys.stderr)
            return 1

    interval = poll_interval if poll_interval is not None else cfg.daemon_poll_interval
    settle = settle_seconds if settle_seconds is not None else cfg.daemon_settle_seconds
    stages = resolve_stages(args, cfg)

    watcher = RecorderWatcher(
        cfg=cfg,
        stages=stages,
        poll_interval=interval,
        settle_seconds=settle,
        force=getattr(args, "force", False),
    )

    def _handle_signal(signum, _frame) -> None:
        print(f"\n🛑 Stopping daemon (signal {signum})")
        watcher.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    return watcher.run()