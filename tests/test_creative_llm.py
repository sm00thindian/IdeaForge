"""Tests for creative output parsing in the LLM layer."""

from pathlib import Path

from ideaforge.config import CreativePlatformStyle, CreativeSettings
from ideaforge.llm import _dict_to_creative, _resolve_pipeline_mode


def test_resolve_pipeline_mode_detects_song_idea():
    settings = CreativeSettings(trigger_phrases=["song idea"])
    mode, intent = _resolve_pipeline_mode(
        "auto",
        "Song idea. Folk ballad about the river.",
        settings,
    )
    assert mode == "creative"
    assert intent is not None
    assert intent.matched_phrase == "song idea"


def test_resolve_pipeline_mode_meeting_default():
    settings = CreativeSettings(trigger_phrases=["song idea"])
    mode, intent = _resolve_pipeline_mode(
        "auto",
        "Sprint planning for Q3 deliverables.",
        settings,
    )
    assert mode == "meeting"


def test_dict_to_creative_applies_platform_formatting():
    data = {
        "title": "River Song",
        "creative_summary": "A wistful folk ballad.",
        "detected_style": "acoustic folk",
        "chorus_hook": "The river knows my name",
        "suno_style_prompt": "acoustic folk, fingerpicked guitar, warm male vocal, river mood",
        "suno_lyrics_prompt": "[verse 1]\nDown by the water\n[chorus]\nThe river knows my name",
        "udio_prompt": "River memories",
        "raw_lyric_fragments": ["down by the water"],
    }
    output = _dict_to_creative(
        data,
        Path("R2026-06-27.txt"),
        creative_settings=CreativeSettings(style_merge="merge"),
        suno_style=CreativePlatformStyle(style_default="intimate, 80 BPM"),
        udio_style=CreativePlatformStyle(style_default="folk, mellow"),
    )
    assert output.intent == "song_idea"
    assert output.suno_style_prompt
    assert len(output.suno_style_prompt) <= 1000
    assert "[Verse 1]" in (output.suno_lyrics_prompt or "")
    assert output.udio_prompt
    assert output.udio_lyrics