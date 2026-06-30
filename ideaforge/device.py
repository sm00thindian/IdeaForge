"""USB voice recorder detection (Z28/Z29 and similar exFAT devices)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ideaforge.config import IdeaForgeConfig
    from ideaforge.device_profiles import DeviceProfile

# Z28/Z29 recorders store WAV files as RYYYY-MM-DD-HH-MM-SS.WAV in RECORD/
RECORDING_PATTERN = re.compile(r"^R\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.WAV$", re.IGNORECASE)
KNOWN_RECORD_FOLDERS = ("RECORD", "Record", "record")
SETTINGS_FILES = ("recset.txt", "RECSET.TXT")
RECSET_TIME_PATTERN = re.compile(
    r"TIME:\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(\d{4})/(\d{1,2})/(\d{1,2})",
    re.IGNORECASE,
)


@dataclass
class RecorderDevice:
    mount_path: Path
    record_folder: Path
    settings_file: Optional[Path]
    recording_count: int
    device_name: Optional[str] = None
    profile_name: str = "z28"
    profile: Optional["DeviceProfile"] = None

    @property
    def label(self) -> str:
        if self.device_name:
            return f"{self.device_name} ({self.mount_path.name})"
        return self.mount_path.name


def is_recorder_volume(volume: Path) -> bool:
    """Heuristic: volume contains RECORD/ with R*.WAV files or recset.txt."""
    if not volume.is_dir():
        return False
    for folder_name in KNOWN_RECORD_FOLDERS:
        record_dir = volume / folder_name
        if record_dir.is_dir():
            wavs = list(record_dir.glob("R*.WAV")) + list(record_dir.glob("R*.wav"))
            if wavs:
                return True
    for settings in SETTINGS_FILES:
        if (volume / settings).is_file():
            return True
    return False


def find_recorder_mounts(
    volumes_root: Path = Path("/Volumes"),
    cfg: Optional["IdeaForgeConfig"] = None,
) -> List[RecorderDevice]:
    """Scan macOS /Volumes for attached USB recorders."""
    from ideaforge.device_registry import find_recorder_mounts as _find

    return _find(volumes_root, cfg)


def auto_detect_source(
    volumes_root: Path = Path("/Volumes"),
    cfg: Optional["IdeaForgeConfig"] = None,
) -> Optional[Path]:
    """Return mount path of the sole detected recorder, or None."""
    devices = find_recorder_mounts(volumes_root, cfg)
    if len(devices) == 1:
        return devices[0].mount_path
    return None


def _find_record_folder(volume: Path) -> Optional[Path]:
    for name in KNOWN_RECORD_FOLDERS:
        path = volume / name
        if path.is_dir():
            return path
    return None


def _find_settings_file(volume: Path) -> Optional[Path]:
    for name in SETTINGS_FILES:
        path = volume / name
        if path.is_file():
            return path
    return None


def is_path_on_recorder(file_path: Path, volumes_root: Path = Path("/Volumes")) -> bool:
    """True if file_path lives on a detected USB recorder volume."""
    try:
        resolved = file_path.resolve()
    except OSError:
        return False
    parts = resolved.parts
    if len(parts) < 3 or parts[0] != "/" or parts[1] != "Volumes":
        return False
    volume = volumes_root / parts[2]
    return is_recorder_volume(volume)


def unmount_volume(mount_path: Path) -> bool:
    """Unmount a recorder volume after ingest (macOS diskutil)."""
    if not mount_path.is_dir():
        return False
    try:
        completed = subprocess.run(
            ["diskutil", "unmount", str(mount_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, FileNotFoundError):
        return False
    return completed.returncode == 0


@dataclass(frozen=True)
class DeviceClockInfo:
    device_label: str
    settings_file: Path
    device_time: datetime
    system_time: datetime

    @property
    def skew_seconds(self) -> float:
        return (self.device_time - self.system_time).total_seconds()


def parse_recset_time(settings_path: Path) -> Optional[datetime]:
    """Parse device wall clock from recset.txt (e.g. TIME:14:24 2025/7/7)."""
    try:
        text = settings_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    for line in text.splitlines():
        match = RECSET_TIME_PATTERN.search(line)
        if not match:
            continue
        hour, minute, second, year, month, day = match.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
        )
    return None


def device_from_mount(
    mount: Path,
    cfg: Optional["IdeaForgeConfig"] = None,
) -> Optional[RecorderDevice]:
    """Build a RecorderDevice from a mount path, or None if not a recorder."""
    from ideaforge.config import IdeaForgeConfig
    from ideaforge.device_registry import discover_mount

    return discover_mount(mount.expanduser().resolve(), cfg or IdeaForgeConfig())


def format_recset_time_line(dt: datetime) -> str:
    """Format a TIME line for recset.txt (Z28 style, e.g. TIME:14:24 2025/7/7)."""
    if dt.second:
        time_part = f"{dt.hour}:{dt.minute:02d}:{dt.second:02d}"
    else:
        time_part = f"{dt.hour}:{dt.minute:02d}"
    return f"TIME:{time_part} {dt.year}/{dt.month}/{dt.day}"


def update_recset_time(settings_path: Path, new_time: datetime) -> bool:
    """Replace or append the TIME: line in recset.txt; preserve other settings."""
    new_line = format_recset_time_line(new_time)
    try:
        text = settings_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    lines = text.splitlines()
    out: List[str] = []
    replaced = False
    for line in lines:
        if RECSET_TIME_PATTERN.search(line) or line.strip().upper().startswith("TIME:"):
            if not replaced:
                out.append(new_line)
                replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(new_line)

    try:
        settings_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class ClockSyncResult:
    updated: bool
    skipped: bool
    reason: str
    info: Optional[DeviceClockInfo] = None
    previous_time: Optional[datetime] = None
    new_time: Optional[datetime] = None


def sync_device_clock(
    device: RecorderDevice,
    *,
    max_skew_seconds: float = 60.0,
    force: bool = False,
) -> ClockSyncResult:
    """Update recset.txt when device clock skew exceeds the threshold."""
    if device.settings_file is None:
        return ClockSyncResult(
            updated=False,
            skipped=True,
            reason="no recset.txt",
        )

    info = read_device_clock(device)
    if info is None:
        return ClockSyncResult(
            updated=False,
            skipped=True,
            reason="could not parse TIME line",
        )

    if not force and abs(info.skew_seconds) <= max_skew_seconds:
        return ClockSyncResult(
            updated=False,
            skipped=True,
            reason=f"within {max_skew_seconds:g}s threshold",
            info=info,
        )

    previous = info.device_time
    new_time = datetime.now().replace(microsecond=0)
    if not update_recset_time(device.settings_file, new_time):
        return ClockSyncResult(
            updated=False,
            skipped=False,
            reason="failed to write recset.txt",
            info=info,
            previous_time=previous,
        )

    return ClockSyncResult(
        updated=True,
        skipped=False,
        reason=_format_skew(info.skew_seconds),
        info=info,
        previous_time=previous,
        new_time=new_time,
    )


def read_device_clock(device: RecorderDevice) -> Optional[DeviceClockInfo]:
    """Read recset.txt clock and compare to local system time."""
    if device.settings_file is None:
        return None
    device_time = parse_recset_time(device.settings_file)
    if device_time is None:
        return None
    return DeviceClockInfo(
        device_label=device.label,
        settings_file=device.settings_file,
        device_time=device_time,
        system_time=datetime.now(),
    )


def _format_skew(seconds: float) -> str:
    magnitude = abs(seconds)
    if magnitude < 60:
        detail = f"{int(magnitude)} second(s)"
    elif magnitude < 3600:
        detail = f"{int(magnitude // 60)} minute(s)"
    elif magnitude < 86_400:
        detail = f"{magnitude / 3600:.1f} hour(s)"
    else:
        detail = f"{magnitude / 86_400:.1f} day(s)"
    if abs(seconds) < 2:
        return f"in sync ({detail})"
    direction = "ahead of" if seconds > 0 else "behind"
    return f"{detail} {direction} system time"


def format_device_clock_report(info: DeviceClockInfo) -> str:
    lines = [
        f"Recorder:     {info.device_label}",
        f"Settings:     {info.settings_file}",
        f"Device time:  {info.device_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"System time:  {info.system_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Skew:         {_format_skew(info.skew_seconds)}",
        "",
        "Filenames use the device clock. Fix the date on the recorder if skew is large.",
        "IdeaForge archive folders follow filename stems, not LLM-inferred dates.",
    ]
    return "\n".join(lines)


def run_device_clock(
    source: Optional[Path] = None,
    *,
    sync: bool = False,
    force_sync: bool = False,
    max_skew_seconds: float = 60.0,
) -> int:
    """CLI entry: show recorder clock skew vs system time; optionally sync recset.txt."""
    if source is not None:
        device = device_from_mount(source.expanduser().resolve())
        if device is None:
            print(f"❌ Not a recorder mount: {source}")
            return 1
    else:
        devices = find_recorder_mounts()
        if not devices:
            print("❌ No USB recorders detected under /Volumes")
            return 1
        if len(devices) > 1:
            names = ", ".join(device.label for device in devices)
            print(f"❌ Multiple recorders detected ({names}) — unplug extras or use --source")
            return 1
        device = devices[0]

    if device.settings_file is None:
        print(f"❌ No recset.txt on {device.label}")
        return 1

    info = read_device_clock(device)
    if info is None:
        print(f"❌ Could not parse TIME from {device.settings_file}")
        return 1

    print(format_device_clock_report(info))

    if not sync:
        return 0

    sync_result = sync_device_clock(
        device,
        max_skew_seconds=max_skew_seconds,
        force=force_sync,
    )
    if sync_result.updated and sync_result.new_time is not None:
        print(
            f"\n✓ Updated {device.settings_file.name} to "
            f"{sync_result.new_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return 0
    if sync_result.skipped:
        print(f"\n   Clock sync skipped: {sync_result.reason}")
        return 0

    print(f"\n❌ Clock sync failed: {sync_result.reason}")
    return 1


def describe_device(device: RecorderDevice) -> str:
    lines = [
        f"  Mount:      {device.mount_path}",
        f"  Label:      {device.label}",
        f"  Profile:    {device.profile_name}",
        f"  Recordings: {device.recording_count} in {device.record_folder.name}/",
    ]
    if device.device_name:
        lines.append(f"  Config:     {device.device_name}")
    if device.settings_file:
        lines.append(f"  Settings:   {device.settings_file.name}")
    return "\n".join(lines)