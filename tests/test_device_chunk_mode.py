"""Tests for per-device chunk_mode overrides."""

from ideaforge.config import DeviceBinding, IdeaForgeConfig
from ideaforge.device_registry import device_name_for_archive_root, resolve_chunk_mode


def test_resolve_chunk_mode_device_override(tmp_path):
    archive = tmp_path / "IdeaForge"
    cfg = IdeaForgeConfig(
        archive=archive,
        chunk_mode="gap",
        devices=[
            DeviceBinding(name="field", mount_glob="REC", profile="generic_wav", chunk_mode="fixed_window"),
            DeviceBinding(name="z28", mount_glob="NO NAME", profile="z28"),
        ],
    )
    assert resolve_chunk_mode(cfg, "field") == "fixed_window"
    assert resolve_chunk_mode(cfg, "z28") == "gap"
    assert resolve_chunk_mode(cfg, None) == "gap"


def test_device_name_for_archive_root(tmp_path):
    archive = tmp_path / "IdeaForge"
    z28 = archive / "z28"
    z28.mkdir(parents=True)
    cfg = IdeaForgeConfig(
        archive=archive,
        devices=[DeviceBinding(name="z28", mount_glob="NO NAME", profile="z28")],
    )
    assert device_name_for_archive_root(cfg, z28) == "z28"
    assert device_name_for_archive_root(cfg, archive) is None