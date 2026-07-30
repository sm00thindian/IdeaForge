"""Tests for song-idea prompt building."""

from ideaforge.config import CreativePlatformStyle, CreativeSettings
from ideaforge.prompts import build_prompt, build_song_idea_prompt


def test_song_idea_prompt_includes_style_config():
    system, user = build_song_idea_prompt(
        "lo-fi song about rain on the window",
        suno_style=CreativePlatformStyle(
            style_default="lo-fi, warm piano",
            style_variations=["late night, 70 BPM"],
        ),
        udio_style=CreativePlatformStyle(
            style_default="jazz, mellow",
            style_variations=[],
        ),
    )
    assert "lyricist" in system.lower()
    assert "warm piano" in user
    assert "late night" in user
    assert "rain on the window" in user
    assert "suno_lyrics_prompt" in user
    assert "udio_prompt" in user


def test_song_idea_prompt_includes_duration_and_rhyme_targets():
    system, user = build_song_idea_prompt(
        "ballad about leaving home",
        suno_style=CreativePlatformStyle(style_default="folk"),
        udio_style=CreativePlatformStyle(style_default="folk"),
        creative_settings=CreativeSettings(
            target_duration_minutes=4.5,
            rhyme_scheme="abab",
        ),
    )
    assert "4.5" in system
    assert "ABAB" in system or "abab" in system.lower()
    assert "rhyme_scheme" in user
    assert "Verse 3" in system or "verse" in system.lower()


def test_build_prompt_routes_song_idea_content():
    _, user = build_prompt(
        "meeting",
        "ignored transcript",
        song_idea_content="ballad about leaving home",
        suno_style=CreativePlatformStyle(style_default="folk"),
        udio_style=CreativePlatformStyle(style_default="folk"),
    )
    assert "leaving home" in user
    assert "suno_style_prompt" in user