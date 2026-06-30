"""USB voice recorder detection (Z28/Z29 and similar exFAT devices)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

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

    @property
    def label(self) -> str:
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


def find_recorder_mounts(volumes_root: Path = Path("/Volumes")) -> List[RecorderDevice]:
    """Scan macOS /Volumes for attached USB recorders."""
    devices: List[RecorderDevice] = []
    if not volumes_root.is_dir():
        return devices

    for volume in sorted(volumes_root.iterdir()):
        if volume.name.startswith(".") or volume.is_symlink():
            continue
        if not is_recorder_volume(volume):
            continue

        record_folder = _find_record_folder(volume)
        settings = _find_settings_file(volume)
        count = len(list(record_folder.glob("R*.WAV")) + list(record_folder.glob("R*.wav"))) if record_folder else 0

        devices.append(
            RecorderDevice(
                mount_path=volume,
                record_folder=record_folder or volume,
                settings_file=settings,
                recording_count=count,
            )
        )
    return devices


def auto_detect_source(volumes_root: Path = Path("/Volumes")) -> Optional[Path]:
    """Return mount path of the sole detected recorder, or None."""
    devices = find_recorder_mounts(volumes_root)
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


def device_from_mount(mount: Path) -> Optional[RecorderDevice]:
    """Build a RecorderDevice from a mount path, or None if not a recorder."""
    if not is_recorder_volume(mount):
        return None
    record_folder = _find_record_folder(mount)
    settings = _find_settings_file(mount)
    count = 0
    if record_folder:
        count = len(
            list(record_folder.glob("R*.WAV")) + list(record_folder.glob("R*.wav"))
        )
    return RecorderDevice(
        mount_path=mount,
        record_folder=record_folder or mount,
        settings_file=settings,
        recording_count=count,
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


def run_device_clock(source: Optional[Path] = None) -> int:
    """CLI entry: show recorder clock skew vs system time."""
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
    return 0


def describe_device(device: RecorderDevice) -> str:
    lines = [
        f"  Mount:      {device.mount_path}",
        f"  Label:      {device.label}",
        f"  Recordings: {device.recording_count} in {device.record_folder.name}/",
    ]
    if device.settings_file:
        lines.append(f"  Settings:   {device.settings_file.name}")
    return "\n".join(lines)