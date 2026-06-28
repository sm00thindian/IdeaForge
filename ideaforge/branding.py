"""Bundled IdeaForge branding assets."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path


@lru_cache(maxsize=1)
def assets_dir() -> Path:
    return Path(resources.files("ideaforge")).joinpath("assets")


def asset_path(name: str) -> Path:
    path = assets_dir() / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing IdeaForge asset: {name}")
    return path


def notification_icon_path() -> Path:
    """PNG icon for macOS notifications (128px)."""
    preferred = assets_dir() / "icon-128.png"
    if preferred.is_file():
        return preferred
    return asset_path("icon.png")