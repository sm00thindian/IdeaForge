"""LLM backends and structured output processing."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ideaforge.config import has_anthropic_api_key, has_xai_api_key
from ideaforge.session_time import ResolvedRecordingTime
from ideaforge.export import ExportSettings, export_action_items
from ideaforge.summary_names import (
    action_preview_lines,
    creative_preview_lines,
    legacy_summary_md_path,
    plan_summary_md_path,
    resolve_summary_md_path,
)
from ideaforge.prompts import Mode, build_lyric_polish_prompt, build_prompt
from ideaforge.creative_intent import IntentResult, detect_intent, is_song_idea
from ideaforge.creative_platforms import (
    PlatformStyleConfig,
    apply_platform_formatting,
    write_platform_sidecars,
)
from ideaforge.status import Stage, active_reporter, status_touch
from ideaforge.schema import (
    ActionItem,
    CreativeOutput,
    CreativeSpark,
    Decision,
    DiscussionTopic,
    FollowUp,
    MeetingNotes,
    SpeakerContribution,
    SpeakerIdentity,
)

if TYPE_CHECKING:
    from ideaforge.config import CreativePlatformStyle, CreativeSettings

try:
    import ollama
except ImportError:
    ollama = None  # type: ignore

try:
    import openai
except ImportError:
    openai = None  # type: ignore

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore


def _resolve_pipeline_mode(
    mode: Mode,
    transcript: str,
    creative_settings: Optional["CreativeSettings"],
) -> tuple[str, Optional[IntentResult]]:
    """Return (effective_mode, intent_result). effective_mode is meeting or creative."""
    if mode == "meeting":
        return "meeting", None
    if mode == "creative":
        return "creative", None
    if mode == "auto" and creative_settings and creative_settings.enabled:
        intent = detect_intent(
            transcript,
            creative_settings.trigger_phrases,
            scan_chars=creative_settings.scan_chars,
        )
        if is_song_idea(intent):
            return "creative", intent
        return "meeting", intent
    return "meeting", None


def process_transcript(
    transcript_path: Path,
    output_dir: Path,
    mode: Mode = "meeting",
    backend: str = "auto",
    ollama_model: str = "llama3.1",
    grok_model: str = "grok-4.3",
    claude_model: str = "claude-sonnet-4-20250514",
    output_format: str = "both",
    force: bool = False,
    archive: Optional[Path] = None,
    export_settings: Optional[ExportSettings] = None,
    recording_time: Optional["ResolvedRecordingTime"] = None,
    creative_settings: Optional["CreativeSettings"] = None,
    suno_style: Optional["CreativePlatformStyle"] = None,
    udio_style: Optional["CreativePlatformStyle"] = None,
    meeting_domain: str = "auto",
    meeting_domain_terms: Optional[List[str]] = None,
) -> Optional[Path]:
    """Generate structured output from a transcript. Returns primary output path."""
    stem = transcript_path.stem
    json_path = output_dir / f"{stem}_summary.json"
    existing_md = resolve_summary_md_path(output_dir, stem)

    if not force:
        if output_format == "md" and existing_md is not None:
            print("    ↳ Summary exists → skipping")
            return existing_md
        if output_format == "json" and json_path.exists():
            print("    ↳ Summary exists → skipping")
            return json_path
        if (
            output_format == "both"
            and existing_md is not None
            and json_path.exists()
        ):
            print("    ↳ Summary exists → skipping")
            return existing_md

    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if len(transcript) < 50:
        print("    ⚠️  Transcript too short for LLM processing")
        return None

    effective_mode, intent_result = _resolve_pipeline_mode(
        mode, transcript, creative_settings
    )
    if effective_mode == "creative":
        if intent_result and intent_result.matched_phrase:
            print(f"    🎵 Song idea detected ({intent_result.matched_phrase!r})")
        else:
            print("    🎵 Song idea mode")
        reporter = active_reporter()
        if reporter is not None:
            reporter.set_output_intent("song_idea")
    else:
        print("    📋 Meeting notes")

    song_idea_content: Optional[str] = None
    if effective_mode == "creative":
        if intent_result and intent_result.content_after_trigger:
            song_idea_content = intent_result.content_after_trigger
        else:
            song_idea_content = transcript

    resolved_domain = meeting_domain
    if effective_mode != "creative":
        from ideaforge.meeting_domain import resolve_meeting_domain

        detection = resolve_meeting_domain(meeting_domain, transcript)
        resolved_domain = detection.domain
        if detection.matched:
            print(
                f"    🏛  Meeting domain: {resolved_domain} "
                f"({detection.reason}; matched: {', '.join(detection.matched[:5])})"
            )
        else:
            print(f"    🏛  Meeting domain: {resolved_domain} ({detection.reason})")

    resolved_backend = _resolve_backend(backend)
    temperature = (
        creative_settings.temperature
        if effective_mode == "creative" and creative_settings
        else 0.2
    )
    status_touch(
        stage=Stage.SUMMARIZING,
        clear_progress=True,
        detail=f"{resolved_backend} · {transcript_path.stem}",
    )
    rec_date = recording_time.iso_date if recording_time is not None else None
    rec_src = recording_time.source if recording_time is not None else None
    system_prompt, user_prompt = build_prompt(
        "creative" if effective_mode == "creative" else "meeting",
        transcript,
        song_idea_content=song_idea_content,
        suno_style=suno_style,
        udio_style=udio_style,
        creative_settings=creative_settings,
        meeting_domain=resolved_domain,
        meeting_domain_terms=meeting_domain_terms,
        recording_date=rec_date,
        recording_date_source=rec_src,
    )

    models = {
        "ollama": ollama_model,
        "grok": grok_model,
        "claude": claude_model,
    }
    used_backend = resolved_backend
    used_model = models.get(resolved_backend, ollama_model)

    try:
        raw = _call_llm(
            resolved_backend,
            system_prompt,
            user_prompt,
            temperature=temperature,
            ollama_model=ollama_model,
            grok_model=grok_model,
            claude_model=claude_model,
            creative=effective_mode == "creative",
        )
    except Exception as exc:
        if resolved_backend in ("grok", "claude") and _ollama_available():
            label = "Grok" if resolved_backend == "grok" else "Claude"
            print(f"    ⚠️  {label} failed ({exc}) — retrying with Ollama")
            try:
                raw = _call_llm(
                    "ollama",
                    system_prompt,
                    user_prompt,
                    temperature=temperature,
                    ollama_model=ollama_model,
                    grok_model=grok_model,
                    claude_model=claude_model,
                    creative=effective_mode == "creative",
                )
                used_backend = "ollama"
                used_model = ollama_model
            except Exception as fallback_exc:
                print(f"    ❌ LLM error: {fallback_exc}")
                return None
        else:
            print(f"    ❌ LLM error: {exc}")
            return None

    parsed = _parse_json_response(raw or "")
    if not parsed:
        md_path = plan_summary_md_path(
            folder=output_dir,
            session_stem=stem,
            title=stem,
            iso_date=recording_time.iso_date if recording_time else "",
            output_intent="song_idea" if effective_mode == "creative" else None,
        )
        md_path.write_text((raw or "").strip(), encoding="utf-8")
        print(f"    ✓ Raw summary saved (non-JSON response): {md_path.name}")
        return md_path

    multi_pass_applied = False
    if (
        effective_mode == "creative"
        and creative_settings is not None
        and creative_settings.multi_pass
    ):
        polished = _run_creative_polish_pass(
            parsed,
            backend=used_backend,
            temperature=temperature,
            ollama_model=ollama_model,
            grok_model=grok_model,
            claude_model=claude_model,
            creative_settings=creative_settings,
        )
        if polished is not None:
            parsed = polished
            multi_pass_applied = True
            print("    ✨ Lyric polish pass complete")
        else:
            print("    ⚠️  Lyric polish pass skipped (non-JSON or error) — keeping draft")

    resolved_mode = effective_mode
    if mode == "auto" and effective_mode == "meeting":
        resolved_mode = _resolve_mode(parsed, mode)

    if multi_pass_applied:
        meta = parsed.setdefault("metadata", {})
        if isinstance(meta, dict):
            meta["multi_pass"] = True

    primary_path = _write_structured_output(
        parsed,
        resolved_mode,
        output_dir,
        json_path,
        output_format,
        transcript_path,
        llm_backend=used_backend,
        llm_model=used_model,
        archive=archive,
        export_settings=export_settings,
        recording_time=recording_time,
        creative_settings=creative_settings,
        suno_style=suno_style,
        udio_style=udio_style,
        intent_result=intent_result,
    )
    return primary_path


def _run_creative_polish_pass(
    draft: Dict[str, Any],
    *,
    backend: str,
    temperature: float,
    ollama_model: str,
    grok_model: str,
    claude_model: str,
    creative_settings: "CreativeSettings",
) -> Optional[Dict[str, Any]]:
    """Optional second LLM call to polish creative draft JSON."""
    system_prompt, user_prompt = build_lyric_polish_prompt(
        draft,
        creative_settings=creative_settings,
    )
    status_touch(
        stage=Stage.SUMMARIZING,
        detail="lyric polish pass",
    )
    try:
        raw = _call_llm(
            backend,
            system_prompt,
            user_prompt,
            temperature=min(temperature, 0.5),
            ollama_model=ollama_model,
            grok_model=grok_model,
            claude_model=claude_model,
            creative=True,
        )
    except Exception as exc:
        print(f"    ⚠️  Polish pass failed: {exc}")
        return None
    polished = _parse_json_response(raw or "")
    if not polished:
        return None
    return _merge_creative_polish(draft, polished)


def _merge_creative_polish(
    draft: Dict[str, Any],
    polished: Dict[str, Any],
) -> Dict[str, Any]:
    """Prefer polished lyric fields; keep draft keys if polish omitted them."""
    merged = dict(draft)
    for key in (
        "title",
        "creative_summary",
        "themes",
        "chorus_hook",
        "chorus_variants",
        "lyrics_draft",
        "suno_style_prompt",
        "suno_lyrics_prompt",
        "udio_prompt",
        "udio_lyrics",
        "rhyme_scheme",
        "detected_style",
        "raw_lyric_fragments",
        "sparks",
    ):
        if key in polished and polished[key] not in (None, "", []):
            merged[key] = polished[key]
    return merged


def _resolve_backend(backend: str) -> str:
    if backend == "auto":
        return "grok" if has_xai_api_key() else "ollama"
    if backend == "grok" and not has_xai_api_key():
        print("    ⚠️  XAI_API_KEY not set — falling back to Ollama")
        return "ollama"
    if backend == "claude" and not has_anthropic_api_key():
        print("    ⚠️  ANTHROPIC_API_KEY not set — falling back to Ollama")
        return "ollama"
    return backend


def _ollama_available() -> bool:
    return ollama is not None


def _call_llm(
    backend: str,
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float,
    ollama_model: str,
    grok_model: str,
    claude_model: str,
    creative: bool = False,
) -> str:
    if backend == "grok":
        return _call_grok(
            system_prompt, user_prompt, grok_model,
            temperature=temperature, creative=creative,
        )
    if backend == "claude":
        return _call_claude(
            system_prompt, user_prompt, claude_model,
            temperature=temperature, creative=creative,
        )
    return _call_ollama(
        system_prompt, user_prompt, ollama_model, temperature=temperature,
    )


def _call_grok(
    system_prompt: str,
    user_prompt: str,
    grok_model: str,
    *,
    temperature: float,
    creative: bool = False,
) -> str:
    if openai is None:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY environment variable not set")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    label = "song idea" if creative else "meeting analysis"
    print(f"    🤖 xAI Grok ({grok_model}) — {label}")
    response = client.chat.completions.create(
        model=grok_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def _call_claude(
    system_prompt: str,
    user_prompt: str,
    claude_model: str,
    *,
    temperature: float,
    creative: bool = False,
) -> str:
    if anthropic is None:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")
    client = anthropic.Anthropic(api_key=api_key)
    label = "song idea" if creative else "meeting analysis"
    print(f"    🤖 Anthropic Claude ({claude_model}) — {label}")
    response = client.messages.create(
        model=claude_model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=temperature,
    )
    parts = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def _call_ollama(
    system_prompt: str,
    user_prompt: str,
    ollama_model: str,
    *,
    temperature: float,
) -> str:
    if ollama is None:
        raise RuntimeError("ollama package not installed. Run: pip install ollama")
    print(f"    🤖 Ollama ({ollama_model})")
    client = ollama.Client()
    response = client.chat(
        model=ollama_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        options={"temperature": temperature},
    )
    return response["message"]["content"]


def _parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass
    return None


def _resolve_mode(parsed: Dict[str, Any], requested: Mode) -> str:
    if requested != "auto":
        return requested
    return parsed.get("mode", "meeting")


def _write_structured_output(
    parsed: Dict[str, Any],
    mode: str,
    output_dir: Path,
    json_path: Path,
    output_format: str,
    transcript_path: Path,
    llm_backend: str,
    llm_model: str,
    archive: Optional[Path] = None,
    export_settings: Optional[ExportSettings] = None,
    recording_time: Optional[ResolvedRecordingTime] = None,
    creative_settings: Optional["CreativeSettings"] = None,
    suno_style: Optional["CreativePlatformStyle"] = None,
    udio_style: Optional["CreativePlatformStyle"] = None,
    intent_result: Optional[IntentResult] = None,
) -> Path:
    session_stem = transcript_path.stem
    output_intent: Optional[str] = None
    if mode == "creative":
        output = _dict_to_creative(
            parsed,
            transcript_path,
            recording_time=recording_time,
            creative_settings=creative_settings,
            suno_style=suno_style,
            udio_style=udio_style,
        )
        output_intent = output.intent
        previews = creative_preview_lines(output.to_dict())
    else:
        output = _dict_to_meeting(parsed, transcript_path, recording_time=recording_time)
        previews = action_preview_lines(output.action_items)

    md_path = plan_summary_md_path(
        folder=output_dir,
        session_stem=session_stem,
        title=output.title,
        iso_date=output.date,
        action_preview=previews,
        output_intent=output_intent,
    )

    output.metadata.update({
        "llm_backend": llm_backend,
        "llm_model": llm_model,
        "source_transcript": transcript_path.name,
        "session_stem": session_stem,
        "summary_md": md_path.name,
        "output_intent": output_intent,
    })
    if intent_result and intent_result.matched_phrase:
        output.metadata["trigger_phrase"] = intent_result.matched_phrase
    if recording_time is not None:
        output.metadata.update({
            "recording_date": recording_time.iso_date,
            "recording_date_source": recording_time.source,
        })

    if output_format in ("json", "both"):
        json_path.write_text(
            json.dumps(output.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"    ✓ JSON saved: {json_path.name}")

    if output_format in ("md", "both"):
        md_path.write_text(output.to_markdown(), encoding="utf-8")
        print(f"    ✓ Markdown saved: {md_path.name}")
        # Clean legacy/prior MD in session dir and date-folder notes root.
        for base in {output_dir, md_path.parent}:
            legacy_md = legacy_summary_md_path(base, session_stem)
            if legacy_md != md_path and legacy_md.exists():
                legacy_md.unlink()
        existing = resolve_summary_md_path(output_dir, session_stem)
        if (
            existing is not None
            and existing.resolve() != md_path.resolve()
            and existing.is_file()
        ):
            existing.unlink()

    if mode == "creative" and isinstance(output, CreativeOutput):
        write_platform_sidecars(output_dir, session_stem, output)
        suno_sidecar = output_dir / f"{session_stem}_suno.txt"
        if suno_sidecar.exists():
            print(f"    ✓ Suno sidecar: {suno_sidecar.name}")
        udio_sidecar = output_dir / f"{session_stem}_udio.txt"
        if udio_sidecar.exists():
            print(f"    ✓ Udio sidecar: {udio_sidecar.name}")

    if (
        mode != "creative"
        and isinstance(output, MeetingNotes)
        and export_settings
        and archive
        and output.action_items
    ):
        export_action_items(
            output,
            archive=archive,
            recording_stem=transcript_path.stem,
            settings=export_settings,
        )

    return md_path if output_format != "json" else json_path


def _dict_to_meeting(
    data: Dict[str, Any],
    transcript_path: Path,
    *,
    recording_time: Optional[ResolvedRecordingTime] = None,
) -> MeetingNotes:
    speaker_identities = [
        SpeakerIdentity(
            speaker_id=item.get("speaker_id", "UNKNOWN"),
            inferred_name=item.get("inferred_name", "Unknown"),
            confidence=item.get("confidence", "unknown"),
            rationale=item.get("rationale"),
        )
        for item in data.get("speaker_identities", [])
    ]
    speakers = [
        SpeakerContribution(
            speaker=s.get("speaker", "Unknown"),
            summary=s.get("summary", ""),
            key_quotes=s.get("key_quotes", []),
        )
        for s in data.get("speakers", [])
    ]
    actions = [
        ActionItem(
            who=a.get("who", "Unknown"),
            what=a.get("what", ""),
            when=a.get("when"),
            priority=a.get("priority"),
            confidence=a.get("confidence"),
            source_quote=a.get("source_quote"),
            blocked_by=a.get("blocked_by"),
            notes=a.get("notes"),
            status=a.get("status") or "Open",
        )
        for a in data.get("action_items", [])
    ]
    discussion_topics = [
        DiscussionTopic(
            title=item.get("title", "Discussion"),
            points=item.get("points", []),
        )
        for item in data.get("discussion_topics", [])
        if isinstance(item, dict)
    ]
    decisions = _parse_decisions(data.get("decisions", []))
    follow_ups = _parse_follow_ups(data.get("follow_ups", []))

    authoritative_date = recording_time.iso_date if recording_time else ""
    return MeetingNotes(
        title=data.get("title") or transcript_path.stem,
        date=authoritative_date or data.get("date") or "",
        meeting_type=data.get("meeting_type"),
        time=data.get("time") or None,
        platform=data.get("platform") or None,
        attendees=data.get("attendees") or None,
        executive_summary=data.get("executive_summary", ""),
        topics=data.get("topics", []),
        discussion_topics=discussion_topics,
        preparation_notes=data.get("preparation_notes", []),
        speaker_identities=speaker_identities,
        speakers=speakers,
        key_points=data.get("key_points", []),
        action_items=actions,
        decisions=decisions,
        open_questions=data.get("open_questions", []),
        follow_ups=follow_ups,
        risks_blockers=data.get("risks_blockers", []),
    )


def _parse_decisions(raw: List[Any]) -> List[Decision]:
    decisions: List[Decision] = []
    for item in raw:
        if isinstance(item, str):
            decisions.append(Decision(decision=item))
        elif isinstance(item, dict):
            decisions.append(Decision(
                decision=item.get("decision", ""),
                rationale=item.get("rationale"),
                made_by=item.get("made_by"),
            ))
    return decisions


def _parse_follow_ups(raw: List[Any]) -> List[FollowUp]:
    follow_ups: List[FollowUp] = []
    for item in raw:
        if isinstance(item, str):
            follow_ups.append(FollowUp(topic=item))
        elif isinstance(item, dict):
            follow_ups.append(FollowUp(
                topic=item.get("topic", ""),
                owner=item.get("owner"),
                by_when=item.get("by_when"),
                context=item.get("context"),
            ))
    return follow_ups


def _platform_config_from_creative(
    style: Optional["CreativePlatformStyle"],
) -> PlatformStyleConfig:
    if style is None:
        return PlatformStyleConfig()
    return PlatformStyleConfig(
        style_default=style.style_default,
        style_variations=list(style.style_variations),
    )


def _dict_to_creative(
    data: Dict[str, Any],
    transcript_path: Path,
    *,
    recording_time: Optional[ResolvedRecordingTime] = None,
    creative_settings: Optional["CreativeSettings"] = None,
    suno_style: Optional["CreativePlatformStyle"] = None,
    udio_style: Optional["CreativePlatformStyle"] = None,
) -> CreativeOutput:
    sparks = [
        CreativeSpark(
            title=s.get("title", "Untitled"),
            description=s.get("description", ""),
            genre=s.get("genre"),
            mood=s.get("mood"),
            lyrics_snippet=s.get("lyrics_snippet"),
            suno_prompt=s.get("suno_prompt"),
        )
        for s in data.get("sparks", [])
    ]
    fragments = [
        str(f).strip()
        for f in data.get("raw_lyric_fragments", [])
        if str(f).strip()
    ]

    style_merge = (
        creative_settings.style_merge
        if creative_settings
        else "merge"
    )
    formatted = apply_platform_formatting(
        title=data.get("title") or transcript_path.stem,
        detected_style=data.get("detected_style"),
        suno_style_raw=data.get("suno_style_prompt"),
        suno_lyrics_raw=data.get("suno_lyrics_prompt"),
        udio_prompt_raw=data.get("udio_prompt"),
        udio_lyrics_raw=data.get("udio_lyrics"),
        suno_config=_platform_config_from_creative(suno_style),
        udio_config=_platform_config_from_creative(udio_style),
        style_merge=style_merge,  # type: ignore[arg-type]
    )

    authoritative_date = recording_time.iso_date if recording_time else ""
    return CreativeOutput(
        title=data.get("title") or transcript_path.stem,
        date=authoritative_date or data.get("date") or "",
        creative_summary=data.get("creative_summary", ""),
        themes=data.get("themes", []),
        sparks=sparks,
        intent="song_idea",
        raw_lyric_fragments=fragments,
        detected_style=data.get("detected_style"),
        rhyme_scheme=data.get("rhyme_scheme"),
        applied_style=formatted.get("applied_style"),
        style_variation_index=formatted.get("style_variation_index"),
        chorus_hook=data.get("chorus_hook"),
        chorus_variants=_normalize_chorus_variants(
            data.get("chorus_variants"),
            primary=data.get("chorus_hook"),
            max_count=(
                creative_settings.chorus_variant_count if creative_settings else 3
            ),
        ),
        lyrics_draft=data.get("lyrics_draft"),
        suno_style_prompt=formatted.get("suno_style_prompt"),
        suno_lyrics_prompt=formatted.get("suno_lyrics_prompt"),
        udio_prompt=formatted.get("udio_prompt"),
        udio_lyrics=formatted.get("udio_lyrics"),
    )


def _normalize_chorus_variants(
    raw: Any,
    *,
    primary: Optional[str],
    max_count: int,
) -> List[str]:
    if max_count <= 0 or not raw:
        return []
    if not isinstance(raw, list):
        return []
    primary_norm = (primary or "").strip().lower()
    variants: List[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key == primary_norm or key in seen:
            continue
        seen.add(key)
        variants.append(text)
        if len(variants) >= max_count:
            break
    return variants