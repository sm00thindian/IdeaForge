"""Platform-specific formatters for Suno and Udio creative output."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal, Optional, Sequence, Tuple

StyleMerge = Literal["merge", "memo_wins", "pick_first", "pick_random"]

SUNO_STYLE_MAX_CHARS = 1000

_SECTION_TAG_RE = re.compile(
    r"^\s*(\[(?:verse|chorus|bridge|pre-chorus|outro|intro|hook|drop|instrumental|break)"
    r"(?:\s*\d+)?\s*\])\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class PlatformStyleConfig:
    style_default: str = ""
    style_variations: List[str] = field(default_factory=list)


def merge_style(
    memo_style: Optional[str],
    default: str,
    variations: Sequence[str],
    strategy: StyleMerge,
    *,
    rng: Optional[random.Random] = None,
) -> Tuple[str, Optional[int]]:
    """
    Combine memo-stated style with configured defaults.

    Returns (applied_style, variation_index).
    """
    memo = (memo_style or "").strip()
    base = (default or "").strip()
    vars_clean = [v.strip() for v in variations if v and v.strip()]

    if strategy == "memo_wins":
        if memo:
            return memo, None
        return base or (vars_clean[0] if vars_clean else ""), 0 if vars_clean else None

    if strategy == "pick_first":
        if vars_clean:
            return vars_clean[0], 0
        return base, None

    if strategy == "pick_random":
        pool = [base] + vars_clean if base else list(vars_clean)
        if not pool:
            return memo, None
        picker = rng or random.Random()
        idx = picker.randrange(len(pool))
        if base and idx == 0:
            return pool[0], None
        offset = 0 if base else 0
        var_idx = idx - (1 if base else 0)
        return pool[idx], var_idx if var_idx >= 0 else None

    # merge (default)
    parts: List[str] = []
    if memo:
        parts.append(memo)
    if base:
        parts.append(base)
    elif vars_clean:
        parts.append(vars_clean[0])
    merged = ", ".join(parts)
    var_idx = 0 if (not base and vars_clean) else None
    return merged, var_idx


def clamp_suno_style(text: str, max_chars: int = SUNO_STYLE_MAX_CHARS) -> str:
    """Trim Suno v5.5 style prompt to platform limit (1000 chars including whitespace)."""
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars]
    if ", " in cut:
        return cut.rsplit(", ", 1)[0].strip()
    if " " in cut:
        return cut.rsplit(" ", 1)[0].strip()
    return cut[:max_chars].strip()


def normalize_suno_lyrics(text: str) -> str:
    """Normalize section tags for Suno v5.5 lyrics field."""
    if not text.strip():
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        tag_match = re.match(
            r"^\[(verse|chorus|bridge|pre-chorus|outro|intro|hook|drop|instrumental|break)"
            r"(\s*\d+)?\s*\]$",
            stripped,
            re.IGNORECASE,
        )
        if tag_match:
            label = tag_match.group(1).title().replace("-", "-")
            if tag_match.group(1).lower() == "pre-chorus":
                label = "Pre-Chorus"
            num = (tag_match.group(2) or "").strip()
            out.append(f"[{label}{f' {num}' if num else ''}]".replace("  ", " "))
        else:
            out.append(line.rstrip())
    return "\n".join(out).strip()


def build_udio_prompt(topic: str, style_tags: str) -> str:
    """Udio uses a single prompt: topic + comma-separated style tags."""
    topic_clean = topic.strip()
    tags = ", ".join(t.strip() for t in style_tags.split(",") if t.strip())
    if topic_clean and tags:
        return f"{topic_clean}, {tags}"
    return topic_clean or tags


def normalize_udio_lyrics(text: str) -> str:
    """Light cleanup for Udio custom lyrics editor."""
    return normalize_suno_lyrics(text)


def apply_platform_formatting(
    *,
    title: str,
    detected_style: Optional[str],
    suno_style_raw: Optional[str],
    suno_lyrics_raw: Optional[str],
    udio_prompt_raw: Optional[str],
    udio_lyrics_raw: Optional[str],
    suno_config: PlatformStyleConfig,
    udio_config: PlatformStyleConfig,
    style_merge: StyleMerge,
    rng: Optional[random.Random] = None,
) -> dict:
    """Post-process LLM creative fields into copy-ready platform strings."""
    suno_applied, suno_var_idx = merge_style(
        detected_style or suno_style_raw,
        suno_config.style_default,
        suno_config.style_variations,
        style_merge,
        rng=rng,
    )
    if suno_style_raw and style_merge == "merge":
        suno_applied = clamp_suno_style(
            ", ".join(p for p in [suno_style_raw.strip(), suno_applied] if p)
        )
    else:
        suno_applied = clamp_suno_style(suno_applied)

    udio_applied, udio_var_idx = merge_style(
        detected_style,
        udio_config.style_default,
        udio_config.style_variations,
        style_merge,
        rng=rng,
    )

    suno_lyrics = normalize_suno_lyrics(suno_lyrics_raw or "")
    udio_lyrics = normalize_udio_lyrics(udio_lyrics_raw or suno_lyrics)
    udio_prompt = build_udio_prompt(
        udio_prompt_raw or title,
        udio_applied or (udio_prompt_raw or ""),
    )

    return {
        "applied_style": suno_applied,
        "style_variation_index": suno_var_idx,
        "suno_style_prompt": suno_applied,
        "suno_lyrics_prompt": suno_lyrics,
        "udio_prompt": clamp_suno_style(udio_prompt, max_chars=500),
        "udio_lyrics": udio_lyrics,
        "udio_style_variation_index": udio_var_idx,
    }


def write_platform_sidecars(folder: Path, session_stem: str, output: object) -> None:
    """Write paste-ready Suno and Udio text files beside the session summary."""
    suno_style = getattr(output, "suno_style_prompt", None) or ""
    suno_lyrics = getattr(output, "suno_lyrics_prompt", None) or ""
    udio_prompt = getattr(output, "udio_prompt", None) or ""
    udio_lyrics = getattr(output, "udio_lyrics", None) or ""

    if suno_style or suno_lyrics:
        suno_path = folder / f"{session_stem}_suno.txt"
        blocks = []
        if suno_style:
            blocks.append(f"--- STYLE ---\n{suno_style}")
        if suno_lyrics:
            blocks.append(f"--- LYRICS ---\n{suno_lyrics}")
        suno_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

    if udio_prompt or udio_lyrics:
        udio_path = folder / f"{session_stem}_udio.txt"
        blocks = []
        if udio_prompt:
            blocks.append(f"--- PROMPT ---\n{udio_prompt}")
        if udio_lyrics:
            blocks.append(f"--- LYRICS ---\n{udio_lyrics}")
        udio_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")