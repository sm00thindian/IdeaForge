"""USB recorder watcher daemon — auto-process when device is plugged in."""

from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from ideaforge.config import IdeaForgeConfig
from ideaforge.device import (
    RecorderDevice,
    device_from_mount,
    find_recorder_mounts,
    sync_device_clock,
    unmount_volume,
)
from ideaforge.device_registry import allows_multiple_mounts, archive_device_root
from ideaforge.ingest import (
    IngestResult,
    get_audio_files,
    ingest_device_recordings,
    load_processed_log,
)
from ideaforge.pipeline import PipelineStages, resolve_stages
from ideaforge.notify import ProcessResult, notify_process_complete
from ideaforge.runner import process_source
from ideaforge.status import Stage, StatusReporter


@dataclass(frozen=True)
class DeviceSnapshot:
    """Fingerprint of recorder contents — used to skip redundant pipeline runs."""

    mount_path: str
    recording_count: int
    newest_mtime: float

    @classmethod
    def from_device(cls, device: RecorderDevice) -> "DeviceSnapshot":
        if device.profile is not None:
            return cls(
                mount_path=str(device.mount_path),
                recording_count=device.profile.recording_count(device.mount_path),
                newest_mtime=device.profile.newest_recording_mtime(device.mount_path),
            )
        return cls(
            mount_path=str(device.mount_path),
            recording_count=device.recording_count,
            newest_mtime=0.0,
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
    from ideaforge.ingest import list_device_recordings

    device = device_from_mount(source, cfg)
    remaining = list_device_recordings(source, cfg, device)
    if remaining:
        return False
    label = source.name
    if unmount_volume(source):
        print(f"   📴 Unmounted {label}")
        return True
    print(f"   ⚠️  Could not unmount {label}")
    return False


def _maybe_sync_device_clock(
    source: Path,
    cfg: IdeaForgeConfig,
    reporter: Optional[StatusReporter] = None,
) -> None:
    """Sync recset.txt before ingest so the device clock is correct for future recordings."""
    if not cfg.daemon_sync_device_clock:
        return

    device = device_from_mount(source, cfg)
    if device is None or device.settings_file is None:
        return

    if reporter is not None:
        reporter.enter_processing(device=source.name, stage=Stage.SYNCING_CLOCK)

    result = sync_device_clock(
        device,
        max_skew_seconds=cfg.daemon_clock_skew_threshold_seconds,
    )
    if result.updated and result.previous_time and result.new_time:
        prev = result.previous_time.strftime("%Y-%m-%d %H:%M:%S")
        new = result.new_time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"   🕐 Device clock updated: {prev} → {new}")
    elif result.reason == "failed to write recset.txt":
        print(f"   ⚠️  Could not update device clock: {result.reason}")


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
    _maybe_sync_device_clock(source, cfg, reporter)

    delete = (
        cfg.daemon_delete_after_copy
        if delete_after_copy is None
        else delete_after_copy
    )
    device = device_from_mount(source, cfg)
    ingest = ingest_device_recordings(
        source,
        archive,
        cfg,
        delete_after_copy=delete,
        reporter=reporter,
        device=device,
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
        reporter=reporter,
        device_label=source.name,
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
        devices = find_recorder_mounts(cfg=self.cfg)
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

        if len(current) > 1 and not allows_multiple_mounts(self.cfg):
            names = ", ".join(Path(m).name for m in sorted(current))
            print(f"⚠️  Multiple recorders detected ({names}) — unplug extras")
            self._status.set_idle(detail="Multiple recorders detected — unplug extras")
            return None

        device = self._select_device(devices)
        if device is None:
            if len(devices) == 1:
                idle = devices[0]
                mount_key = str(idle.mount_path)
                if mount_key in self._settled:
                    print(f"   No new recordings on {idle.label} — skipping")
                    self._status.set_watching(device=idle.label)
                    return None
            self._status.set_watching()
            return None

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
            refreshed = find_recorder_mounts(cfg=self.cfg)
            refreshed_device = current.get(mount_key)
            for candidate in refreshed:
                if str(candidate.mount_path) == mount_key:
                    refreshed_device = candidate
                    break
            if refreshed_device is not None:
                device = refreshed_device
                mount_key = str(device.mount_path)
            self._settled.add(mount_key)

        snap = snapshot_device(device)
        if self._last_snapshot.get(mount_key) == snap and not self.force:
            print(f"   No new recordings on {device.label} — skipping")
            self._status.set_watching(device=device.label)
            return None

        archive = archive_device_root(self.cfg, device.device_name)
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
        refreshed = find_recorder_mounts(cfg=self.cfg)
        refreshed_device = None
        for candidate in refreshed:
            if str(candidate.mount_path) == mount_key:
                refreshed_device = candidate
                break
        if refreshed_device is not None:
            self._last_snapshot[mount_key] = snapshot_device(refreshed_device)
        else:
            self._last_snapshot[mount_key] = snap
        return pipeline_result

    def _select_device(self, devices: list[RecorderDevice]) -> Optional[RecorderDevice]:
        """Pick the first device that needs processing this tick."""
        if not devices:
            return None
        if self.force:
            return devices[0]
        for device in devices:
            mount_key = str(device.mount_path)
            snap = snapshot_device(device)
            if mount_key not in self._settled:
                return device
            if self._last_snapshot.get(mount_key) != snap:
                return device
        return None

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