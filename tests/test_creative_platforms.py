"""Tests for Suno/Udio platform formatters."""

from ideaforge.creative_platforms import (
    PlatformStyleConfig,
    apply_platform_formatting,
    clamp_suno_style,
    merge_style,
    normalize_suno_lyrics,
)


def test_clamp_suno_style_at_1000_chars():
    long_style = ", ".join(["acoustic folk"] * 200)
    clamped = clamp_suno_style(long_style, max_chars=1000)
    assert len(clamped) <= 1000


def test_merge_style_combines_memo_and_default():
    applied, _ = merge_style(
        "lo-fi jazz",
        "warm male vocal, upright bass",
        [],
        "merge",
    )
    assert "lo-fi jazz" in applied
    assert "warm male vocal" in applied


def test_merge_style_memo_wins():
    applied, idx = merge_style("cyberpunk synth", "acoustic folk", ["indie"], "memo_wins")
    assert applied == "cyberpunk synth"
    assert idx is None


def test_normalize_suno_lyrics_tags():
    raw = "[verse 1]\nLine one\n[CHORUS]\nHook line"
    normalized = normalize_suno_lyrics(raw)
    assert "[Verse 1]" in normalized
    assert "[Chorus]" in normalized


def test_apply_platform_formatting_produces_udio_prompt():
    formatted = apply_platform_formatting(
        title="Porch Light",
        detected_style="acoustic folk",
        suno_style_raw="acoustic folk, fingerpicked guitar, warm vocal",
        suno_lyrics_raw="[Verse 1]\nFireflies glow\n[Chorus]\nSummer night",
        udio_prompt_raw="Porch light memories",
        udio_lyrics_raw=None,
        suno_config=PlatformStyleConfig(
            style_default="intimate, 85 BPM",
            style_variations=["nostalgic summer"],
        ),
        udio_config=PlatformStyleConfig(
            style_default="folk, mellow",
            style_variations=[],
        ),
        style_merge="merge",
    )
    assert formatted["suno_style_prompt"]
    assert len(formatted["suno_style_prompt"]) <= 1000
    assert "[Verse 1]" in formatted["suno_lyrics_prompt"]
    assert "Porch light" in formatted["udio_prompt"]
    assert formatted["udio_lyrics"]