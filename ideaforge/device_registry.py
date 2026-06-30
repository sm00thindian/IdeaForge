"""Map configured device bindings to mounted volumes and archive roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

from ideaforge.device_profiles import DeviceProfile, get_profile, mount_matches_glob

if TYPE_CHECKING:
    from ideaforge.config import DeviceBinding, IdeaForgeConfig
    from ideaforge.device import RecorderDevice


def archive_device_root(cfg: "IdeaForgeConfig", device_name: Optional[str] = None) -> Path:
    """Per-device archive subdir when ``[[devices]]`` is configured."""
    root = cfg.archive.expanduser().resolve()
    if device_name and cfg.devices:
        return root / device_name
    return root


def device_name_for_archive_root(cfg: "IdeaForgeConfig", archive: Path) -> Optional[str]:
    """Return configured device name when ``archive`` is a per-device archive root."""
    resolved = archive.expanduser().resolve()
    for name, root in list_device_archive_roots(cfg):
        if resolved == root.resolve() and cfg.devices:
            return name
    return None


def resolve_chunk_mode(cfg: "IdeaForgeConfig", device_name: Optional[str]) -> str:
    """Effective chunk_mode for a device (per-device override or global default)."""
    if device_name:
        for binding in cfg.devices:
            if binding.name == device_name and binding.chunk_mode:
                return binding.chunk_mode
    return cfg.chunk_mode


def list_device_archive_roots(cfg: "IdeaForgeConfig") -> List[Tuple[str, Path]]:
    """Return ``(device_name, archive_root)`` pairs for status and fleet aggregation."""
    archive = cfg.archive.expanduser().resolve()
    if cfg.devices:
        return [
            (binding.name, archive_device_root(cfg, binding.name))
            for binding in cfg.devices
        ]
    return [("default", archive)]


def _binding_for_mount(
    mount: Path,
    bindings: List["DeviceBinding"],
) -> Optional["DeviceBinding"]:
    matches = [
        binding
        for binding in bindings
        if mount_matches_glob(mount.name, binding.mount_glob)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _build_recorder_device(
    mount: Path,
    profile: DeviceProfile,
    *,
    device_name: Optional[str],
    profile_name: str,
) -> "RecorderDevice":
    from ideaforge.device import RecorderDevice

    record_folder = profile.scan_root(mount)
    return RecorderDevice(
        mount_path=mount,
        record_folder=record_folder,
        settings_file=profile.settings_file(mount),
        recording_count=profile.recording_count(mount),
        device_name=device_name,
        profile_name=profile_name,
        profile=profile,
    )


def discover_mount(
    mount: Path,
    cfg: "IdeaForgeConfig",
) -> Optional["RecorderDevice"]:
    """Resolve a mount to a configured or default recorder device."""
    if cfg.devices:
        binding = _binding_for_mount(mount, cfg.devices)
        if binding is None:
            return None
        profile = get_profile(binding.profile)
        if not profile.matches_mount(mount):
            return None
        return _build_recorder_device(
            mount,
            profile,
            device_name=binding.name,
            profile_name=binding.profile,
        )

    profile = get_profile("z28")
    if not profile.matches_mount(mount):
        return None
    return _build_recorder_device(
        mount,
        profile,
        device_name=None,
        profile_name="z28",
    )


def find_recorder_mounts(
    volumes_root: Path = Path("/Volumes"),
    cfg: Optional["IdeaForgeConfig"] = None,
) -> List["RecorderDevice"]:
    """Scan volumes and return devices matched by config bindings or legacy z28."""
    from ideaforge.config import IdeaForgeConfig

    config = cfg or IdeaForgeConfig()
    devices: List[RecorderDevice] = []
    if not volumes_root.is_dir():
        return devices

    seen_mounts: set[str] = set()
    for volume in sorted(volumes_root.iterdir()):
        if volume.name.startswith(".") or volume.is_symlink():
            continue
        mount_key = str(volume)
        if mount_key in seen_mounts:
            continue

        if config.devices:
            binding = _binding_for_mount(volume, config.devices)
            if binding is None:
                continue
            profile = get_profile(binding.profile)
            if not profile.matches_mount(volume):
                continue
            devices.append(
                _build_recorder_device(
                    volume,
                    profile,
                    device_name=binding.name,
                    profile_name=binding.profile,
                )
            )
            seen_mounts.add(mount_key)
            continue

        device = discover_mount(volume, config)
        if device is not None:
            devices.append(device)
            seen_mounts.add(mount_key)

    return devices


def allows_multiple_mounts(cfg: "IdeaForgeConfig") -> bool:
    """True when distinct configured devices may be processed in parallel."""
    return bool(cfg.devices)