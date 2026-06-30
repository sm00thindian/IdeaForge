"""LLM backends and structured output processing."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ideaforge.config import has_anthropic_api_key, has_xai_api_key
from ideaforge.export import ExportSettings, export_action_items
from ideaforge.prompts import Mode, build_prompt
from ideaforge.status import Stage, status_touch
from ideaforge.schema import (
    ActionItem,
    CreativeOutput,
    CreativeSpark,
    Decision,
    FollowUp,
    MeetingNotes,
    SpeakerContribution,
    SpeakerIdentity,
)

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
) -> Optional[Path]:
    """Generate structured output from a transcript. Returns primary output path."""
    stem = transcript_path.stem
    md_path = output_dir / f"{stem}_summary.md"
    json_path = output_dir / f"{stem}_summary.json"

    if not force:
        if output_format == "md" and md_path.exists():
            print("    ↳ Summary exists → skipping")
            return md_path
        if output_format == "json" and json_path.exists():
            print("    ↳ Summary exists → skipping")
            return json_path
        if output_format == "both" and md_path.exists() and json_path.exists():
            print("    ↳ Summary exists → skipping")
            return md_path

    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if len(transcript) < 50:
        print("    ⚠️  Transcript too short for LLM processing")
        return None

    resolved_backend = _resolve_backend(backend)
    status_touch(
        stage=Stage.SUMMARIZING,
        clear_progress=True,
        detail=f"{resolved_backend} · {transcript_path.stem}",
    )
    system_prompt, user_prompt = build_prompt(mode, transcript)

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
            ollama_model=ollama_model,
            grok_model=grok_model,
            claude_model=claude_model,
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
                    ollama_model=ollama_model,
                    grok_model=grok_model,
                    claude_model=claude_model,
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
        md_path.write_text((raw or "").strip(), encoding="utf-8")
        print(f"    ✓ Raw summary saved (non-JSON response): {md_path.name}")
        return md_path

    resolved_mode = _resolve_mode(parsed, mode)
    primary_path = _write_structured_output(
        parsed,
        resolved_mode,
        md_path,
        json_path,
        output_format,
        transcript_path,
        llm_backend=used_backend,
        llm_model=used_model,
        archive=archive,
        export_settings=export_settings,
    )
    return primary_path


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
    ollama_model: str,
    grok_model: str,
    claude_model: str,
) -> str:
    if backend == "grok":
        return _call_grok(system_prompt, user_prompt, grok_model)
    if backend == "claude":
        return _call_claude(system_prompt, user_prompt, claude_model)
    return _call_ollama(system_prompt, user_prompt, ollama_model)


def _call_grok(system_prompt: str, user_prompt: str, grok_model: str) -> str:
    if openai is None:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY environment variable not set")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    print(f"    🤖 xAI Grok ({grok_model}) — smart meeting analysis")
    response = client.chat.completions.create(
        model=grok_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def _call_claude(system_prompt: str, user_prompt: str, claude_model: str) -> str:
    if anthropic is None:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")
    client = anthropic.Anthropic(api_key=api_key)
    print(f"    🤖 Anthropic Claude ({claude_model}) — smart meeting analysis")
    response = client.messages.create(
        model=claude_model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.2,
    )
    parts = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def _call_ollama(system_prompt: str, user_prompt: str, ollama_model: str) -> str:
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
    md_path: Path,
    json_path: Path,
    output_format: str,
    transcript_path: Path,
    llm_backend: str,
    llm_model: str,
    archive: Optional[Path] = None,
    export_settings: Optional[ExportSettings] = None,
) -> Path:
    if mode == "creative":
        output = _dict_to_creative(parsed, transcript_path)
    else:
        output = _dict_to_meeting(parsed, transcript_path)

    output.metadata.update({
        "llm_backend": llm_backend,
        "llm_model": llm_model,
        "source_transcript": transcript_path.name,
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


def _dict_to_meeting(data: Dict[str, Any], transcript_path: Path) -> MeetingNotes:
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
        )
        for a in data.get("action_items", [])
    ]
    decisions = _parse_decisions(data.get("decisions", []))
    follow_ups = _parse_follow_ups(data.get("follow_ups", []))

    return MeetingNotes(
        title=data.get("title") or transcript_path.stem,
        date=data.get("date") or "",
        meeting_type=data.get("meeting_type"),
        executive_summary=data.get("executive_summary", ""),
        topics=data.get("topics", []),
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


def _dict_to_creative(data: Dict[str, Any], transcript_path: Path) -> CreativeOutput:
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
    return CreativeOutput(
        title=data.get("title") or transcript_path.stem,
        date=data.get("date") or "",
        creative_summary=data.get("creative_summary", ""),
        themes=data.get("themes", []),
        sparks=sparks,
        lyrics_draft=data.get("lyrics_draft"),
        suno_style_prompt=data.get("suno_style_prompt"),
        suno_lyrics_prompt=data.get("suno_lyrics_prompt"),
    )