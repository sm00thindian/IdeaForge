"""USB voice recorder detection (Z28/Z29 and similar exFAT devices)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Z28/Z29 recorders store WAV files as RYYYY-MM-DD-HH-MM-SS.WAV in RECORD/
RECORDING_PATTERN = re.compile(r"^R\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.WAV$", re.IGNORECASE)
KNOWN_RECORD_FOLDERS = ("RECORD", "Record", "record")
SETTINGS_FILES = ("recset.txt", "RECSET.TXT")


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


def describe_device(device: RecorderDevice) -> str:
    lines = [
        f"  Mount:      {device.mount_path}",
        f"  Label:      {device.label}",
        f"  Recordings: {device.recording_count} in {device.record_folder.name}/",
    ]
    if device.settings_file:
        lines.append(f"  Settings:   {device.settings_file.name}")
    return "\n".join(lines)