"""Tests for bundled branding assets."""

from ideaforge.branding import asset_path, notification_icon_path


def test_icon_assets_exist():
    assert asset_path("icon.svg").is_file()
    assert asset_path("logo.svg").is_file()
    assert asset_path("icon.png").is_file()


def test_notification_icon_prefers_small_png():
    icon = notification_icon_path()
    assert icon.is_file()
    assert icon.name in {"icon-128.png", "icon.png"}