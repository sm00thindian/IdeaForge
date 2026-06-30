"""Device profile protocol and built-in recorder adapters (0.8.0)."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Protocol, Set, runtime_checkable

from ideaforge.chunks import parse_recording_timestamp
from ideaforge.ingest import get_audio_files, is_derived_audio

KNOWN_RECORD_FOLDERS = ("RECORD", "Record", "record")
SETTINGS_FILES = ("recset.txt", "RECSET.TXT")
RECORDING_PATTERN = re.compile(r"^R\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.WAV$", re.IGNORECASE)


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


def _parse_recset_time(settings_path: Path) -> Optional[datetime]:
    from ideaforge.device import parse_recset_time

    return parse_recset_time(settings_path)

BUILTIN_PROFILES = ("z28", "generic_wav")


@runtime_checkable
class DeviceProfile(Protocol):
    """Adapter for vendor-specific USB recorder layout and session identity."""

    @property
    def name(self) -> str: ...

    def matches_mount(self, mount: Path) -> bool: ...

    def discover_files(
        self,
        mount: Path,
        extensions: Set[str],
        min_size_bytes: int,
    ) -> List[Path]: ...

    def parse_session_id(self, path: Path) -> str: ...

    def is_stable_source_file(self, path: Path) -> bool: ...

    def settings_file(self, mount: Path) -> Optional[Path]: ...

    def scan_root(self, mount: Path) -> Path: ...

    def recording_count(self, mount: Path) -> int: ...

    def newest_recording_mtime(self, mount: Path) -> float: ...

    def read_device_clock(self, mount: Path) -> Optional["DeviceClockInfo"]: ...


@dataclass(frozen=True)
class Z28Profile:
    """Z28/Z29 — RECORD/R*.WAV + optional recset.txt."""

    name: str = "z28"

    def matches_mount(self, mount: Path) -> bool:
        if not mount.is_dir():
            return False
        for folder_name in KNOWN_RECORD_FOLDERS:
            record_dir = mount / folder_name
            if record_dir.is_dir():
                wavs = list(record_dir.glob("R*.WAV")) + list(record_dir.glob("R*.wav"))
                if wavs:
                    return True
        for settings in SETTINGS_FILES:
            if (mount / settings).is_file():
                return True
        return False

    def discover_files(
        self,
        mount: Path,
        extensions: Set[str],
        min_size_bytes: int,
    ) -> List[Path]:
        files = get_audio_files(mount, extensions, min_size_bytes)
        return [path for path in files if RECORDING_PATTERN.match(path.name)]

    def parse_session_id(self, path: Path) -> str:
        parsed = parse_recording_timestamp(path)
        if parsed is not None:
            return path.stem
        return path.stem

    def is_stable_source_file(self, path: Path) -> bool:
        return not is_derived_audio(path) and RECORDING_PATTERN.match(path.name) is not None

    def settings_file(self, mount: Path) -> Optional[Path]:
        return _find_settings_file(mount)

    def scan_root(self, mount: Path) -> Path:
        return _find_record_folder(mount) or mount

    def recording_count(self, mount: Path) -> int:
        root = self.scan_root(mount)
        if not root.is_dir():
            return 0
        return len(list(root.glob("R*.WAV")) + list(root.glob("R*.wav")))

    def newest_recording_mtime(self, mount: Path) -> float:
        newest = 0.0
        root = self.scan_root(mount)
        if not root.is_dir():
            return newest
        for pattern in ("R*.WAV", "R*.wav"):
            for wav in root.glob(pattern):
                try:
                    newest = max(newest, wav.stat().st_mtime)
                except OSError:
                    pass
        return newest

    def read_device_clock(self, mount: Path) -> Optional["DeviceClockInfo"]:
        from ideaforge.device import DeviceClockInfo

        settings = self.settings_file(mount)
        if settings is None:
            return None
        device_time = _parse_recset_time(settings)
        if device_time is None:
            return None
        return DeviceClockInfo(
            device_label=mount.name,
            settings_file=settings,
            device_time=device_time,
            system_time=datetime.now(),
        )


@dataclass(frozen=True)
class GenericWavProfile:
    """Generic USB mass storage — recursive audio by mtime, one file per session."""

    name: str = "generic_wav"

    def matches_mount(self, mount: Path) -> bool:
        if not mount.is_dir():
            return False
        for pattern in ("*.wav", "*.WAV", "*.mp3", "*.MP3", "*.m4a", "*.M4A"):
            if any(mount.rglob(pattern)):
                return True
        return False

    def discover_files(
        self,
        mount: Path,
        extensions: Set[str],
        min_size_bytes: int,
    ) -> List[Path]:
        return get_audio_files(mount, extensions, min_size_bytes)

    def parse_session_id(self, path: Path) -> str:
        return path.stem

    def is_stable_source_file(self, path: Path) -> bool:
        return not is_derived_audio(path)

    def settings_file(self, mount: Path) -> Optional[Path]:
        return None

    def scan_root(self, mount: Path) -> Path:
        return mount

    def recording_count(self, mount: Path) -> int:
        return len(self.discover_files(mount, {".wav", ".WAV"}, min_size_bytes=0))

    def newest_recording_mtime(self, mount: Path) -> float:
        files = self.discover_files(mount, {".wav", ".WAV", ".mp3", ".m4a"}, min_size_bytes=0)
        newest = 0.0
        for path in files:
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                pass
        return newest

    def read_device_clock(self, mount: Path) -> Optional["DeviceClockInfo"]:
        return None


_PROFILE_IMPLS: dict[str, DeviceProfile] = {
    "z28": Z28Profile(),
    "generic_wav": GenericWavProfile(),
}


def get_profile(name: str) -> DeviceProfile:
    try:
        return _PROFILE_IMPLS[name]
    except KeyError as exc:
        raise ValueError(f"unknown device profile '{name}'") from exc


def mount_matches_glob(volume_label: str, mount_glob: str) -> bool:
    return fnmatch.fnmatchcase(volume_label, mount_glob)