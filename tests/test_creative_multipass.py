"""Tests for creative multi-pass polish and chorus variants."""

from ideaforge.config import CreativeSettings, IdeaForgeConfig
from ideaforge.llm import _merge_creative_polish, _normalize_chorus_variants
from ideaforge.prompts import build_lyric_polish_prompt, build_song_idea_prompt
from ideaforge.config import CreativePlatformStyle


def test_normalize_chorus_variants_dedupes_primary():
    variants = _normalize_chorus_variants(
        ["Main hook", "Alt one", "main hook", "Alt two", "Alt three"],
        primary="Main hook",
        max_count=3,
    )
    assert variants == ["Alt one", "Alt two", "Alt three"]


def test_normalize_chorus_variants_respects_zero():
    assert (
        _normalize_chorus_variants(["a", "b"], primary="x", max_count=0) == []
    )


def test_merge_creative_polish_prefers_polished_lyrics():
    draft = {
        "title": "Porch",
        "chorus_hook": "old hook",
        "lyrics_draft": "draft lyrics",
        "themes": ["summer"],
    }
    polished = {
        "chorus_hook": "new hook",
        "lyrics_draft": "polished lyrics",
        "chorus_variants": ["v1", "v2"],
    }
    merged = _merge_creative_polish(draft, polished)
    assert merged["title"] == "Porch"
    assert merged["themes"] == ["summer"]
    assert merged["chorus_hook"] == "new hook"
    assert merged["lyrics_draft"] == "polished lyrics"
    assert merged["chorus_variants"] == ["v1", "v2"]


def test_song_prompt_includes_chorus_variants_when_count_positive():
    settings = CreativeSettings(chorus_variant_count=3)
    _, user = build_song_idea_prompt(
        "song idea about rain",
        suno_style=CreativePlatformStyle(style_default="folk"),
        udio_style=CreativePlatformStyle(style_default="folk"),
        creative_settings=settings,
    )
    assert "chorus_variants" in user
    assert "up to 3" in user


def test_song_prompt_empty_variants_when_zero():
    settings = CreativeSettings(chorus_variant_count=0)
    _, user = build_song_idea_prompt(
        "song idea about rain",
        suno_style=CreativePlatformStyle(),
        udio_style=CreativePlatformStyle(),
        creative_settings=settings,
    )
    assert "Leave chorus_variants as an empty array" in user


def test_polish_prompt_includes_draft_json():
    system, user = build_lyric_polish_prompt(
        {"title": "Porch", "lyrics_draft": "verse"},
        creative_settings=CreativeSettings(),
    )
    assert "lyric editor" in system.lower() or "polish" in system.lower()
    assert "Porch" in user
    assert "verse" in user


def test_config_parses_multi_pass_and_variants(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text(
        """
[creative]
multi_pass = true
chorus_variant_count = 4
""".strip(),
        encoding="utf-8",
    )
    cfg = IdeaForgeConfig.from_toml(path)
    assert cfg.creative_multi_pass is True
    assert cfg.creative_chorus_variant_count == 4
    settings = cfg.creative_settings()
    assert settings.multi_pass is True
    assert settings.chorus_variant_count == 4
