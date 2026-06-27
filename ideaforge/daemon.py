"""USB recorder watcher daemon — auto-process when device is plugged in."""

from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from ideaforge.config import IdeaForgeConfig
from ideaforge.device import RecorderDevice, find_recorder_mounts
from ideaforge.pipeline import PipelineStages, resolve_stages
from ideaforge.runner import process_source


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
        process_fn: Callable[..., int] = process_source,
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

    def stop(self) -> None:
        self._running = False

    def tick(self) -> Optional[int]:
        """Single poll cycle. Returns files processed, or None if idle."""
        devices = find_recorder_mounts()
        current = {str(device.mount_path): device for device in devices}
        current_mounts = set(current.keys())

        for mount in sorted(self._connected - current_mounts):
            label = Path(mount).name
            print(f"📴 Recorder disconnected: {label}")
            self._settled.discard(mount)
        self._connected = current_mounts

        if not current:
            return None

        if len(current) > 1:
            names = ", ".join(Path(m).name for m in sorted(current))
            print(f"⚠️  Multiple recorders detected ({names}) — unplug extras")
            return None

        device = next(iter(current.values()))
        mount_key = str(device.mount_path)

        if mount_key not in self._settled:
            print(
                f"📼 Recorder connected: {device.label} "
                f"({device.recording_count} recording(s))"
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
            return None

        archive = self.cfg.archive.expanduser().resolve()
        count = self.process_fn(
            device.mount_path,
            archive,
            self.cfg,
            self.stages,
            force=self.force,
            delete_from_device=self.cfg.daemon_delete_after_copy,
            export_settings=self.cfg.export_settings(force=self.force),
        )
        refreshed = find_recorder_mounts()
        if len(refreshed) == 1:
            self._last_snapshot[mount_key] = snapshot_device(refreshed[0])
        else:
            self._last_snapshot[mount_key] = snap
        return count

    def run(self) -> int:
        from ideaforge import __version__

        print(f"👀 IdeaForge daemon v{__version__}")
        print(f"   Watching /Volumes every {self.poll_interval:.0f}s")
        print(f"   Archive: {self.cfg.archive.expanduser()}")
        print(f"   Pipeline: {self.stages.label}")
        print("   Press Ctrl+C to stop\n")

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
) -> int:
    """Run the recorder watcher until SIGINT/SIGTERM."""
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