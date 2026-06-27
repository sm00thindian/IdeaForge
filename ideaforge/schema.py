"""Structured output schemas for meeting notes and creative modes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActionItem:
    who: str
    what: str
    when: Optional[str] = None
    priority: Optional[str] = None  # high | medium | low
    confidence: Optional[str] = None  # explicit | inferred
    source_quote: Optional[str] = None
    blocked_by: Optional[str] = None


@dataclass
class Decision:
    decision: str
    rationale: Optional[str] = None
    made_by: Optional[str] = None


@dataclass
class FollowUp:
    topic: str
    owner: Optional[str] = None
    by_when: Optional[str] = None
    context: Optional[str] = None


@dataclass
class SpeakerContribution:
    speaker: str
    summary: str
    key_quotes: List[str] = field(default_factory=list)


@dataclass
class MeetingNotes:
    """Structured meeting output — serializable to JSON and rendered to Markdown."""

    title: str
    date: str
    executive_summary: str
    meeting_type: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    speakers: List[SpeakerContribution] = field(default_factory=list)
    key_points: List[str] = field(default_factory=list)
    action_items: List[ActionItem] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    follow_ups: List[FollowUp] = field(default_factory=list)
    risks_blockers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            f"**Date:** {self.date or '—'}",
        ]
        if self.meeting_type:
            lines.append(f"**Type:** {self.meeting_type}")
        lines += ["", "## Executive Summary", "", self.executive_summary, ""]

        if self.topics:
            lines += ["## Topics", ""]
            for topic in self.topics:
                lines.append(f"- {topic}")
            lines.append("")

        if self.speakers:
            lines += ["## Speakers & Contributions", ""]
            for sp in self.speakers:
                lines.append(f"### {sp.speaker}")
                lines.append(sp.summary)
                for quote in sp.key_quotes:
                    lines.append(f"> \"{quote}\"")
                lines.append("")

        if self.key_points:
            lines += ["## Key Points", ""]
            for point in self.key_points:
                lines.append(f"- {point}")
            lines.append("")

        if self.action_items:
            lines += ["## Action Items", ""]
            lines.append("| Who | What | When | Priority | Confidence |")
            lines.append("|-----|------|------|----------|------------|")
            for item in self.action_items:
                lines.append(
                    f"| {item.who} | {item.what} | {item.when or '—'} | "
                    f"{item.priority or '—'} | {item.confidence or '—'} |"
                )
            lines.append("")
            quoted = [i for i in self.action_items if i.source_quote or i.blocked_by]
            if quoted:
                lines += ["### Action Item Details", ""]
                for item in quoted:
                    lines.append(f"- **{item.who}:** {item.what}")
                    if item.source_quote:
                        lines.append(f"  - Source: \"{item.source_quote}\"")
                    if item.blocked_by:
                        lines.append(f"  - Blocked by: {item.blocked_by}")
                lines.append("")

        if self.decisions:
            lines += ["## Decisions", ""]
            for dec in self.decisions:
                if isinstance(dec, Decision):
                    lines.append(f"- **{dec.decision}**")
                    if dec.rationale:
                        lines.append(f"  - Rationale: {dec.rationale}")
                    if dec.made_by:
                        lines.append(f"  - Driven by: {dec.made_by}")
                else:
                    lines.append(f"- {dec}")
            lines.append("")

        if self.risks_blockers:
            lines += ["## Risks & Blockers", ""]
            for risk in self.risks_blockers:
                lines.append(f"- {risk}")
            lines.append("")

        if self.open_questions:
            lines += ["## Open Questions", ""]
            for q in self.open_questions:
                lines.append(f"- {q}")
            lines.append("")

        if self.follow_ups:
            lines += ["## Follow-ups", ""]
            for fu in self.follow_ups:
                if isinstance(fu, FollowUp):
                    owner = f" ({fu.owner})" if fu.owner else ""
                    when = f" — by {fu.by_when}" if fu.by_when else ""
                    lines.append(f"- **{fu.topic}**{owner}{when}")
                    if fu.context:
                        lines.append(f"  - {fu.context}")
                else:
                    lines.append(f"- {fu}")
            lines.append("")

        return "\n".join(lines).strip() + "\n"


@dataclass
class CreativeSpark:
    title: str
    description: str
    genre: Optional[str] = None
    mood: Optional[str] = None
    lyrics_snippet: Optional[str] = None
    suno_prompt: Optional[str] = None


@dataclass
class CreativeOutput:
    """Structured creative output — lyrics, song ideas, Suno prompts."""

    title: str
    date: str
    creative_summary: str
    themes: List[str] = field(default_factory=list)
    sparks: List[CreativeSpark] = field(default_factory=list)
    lyrics_draft: Optional[str] = None
    suno_style_prompt: Optional[str] = None
    suno_lyrics_prompt: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            f"**Date:** {self.date}",
            "",
            "## Creative Summary",
            "",
            self.creative_summary,
            "",
        ]

        if self.themes:
            lines += ["## Themes", ""]
            for theme in self.themes:
                lines.append(f"- {theme}")
            lines.append("")

        if self.sparks:
            lines += ["## Creative Sparks", ""]
            for spark in self.sparks:
                lines.append(f"### {spark.title}")
                if spark.genre or spark.mood:
                    tags = ", ".join(t for t in [spark.genre, spark.mood] if t)
                    lines.append(f"*{tags}*")
                lines.append(spark.description)
                if spark.lyrics_snippet:
                    lines.append(f"\n> {spark.lyrics_snippet}")
                if spark.suno_prompt:
                    lines.append(f"\n**Suno prompt:** {spark.suno_prompt}")
                lines.append("")

        if self.lyrics_draft:
            lines += ["## Lyrics Draft", "", self.lyrics_draft, ""]

        if self.suno_style_prompt:
            lines += ["## Suno Style Prompt", "", f"```\n{self.suno_style_prompt}\n```", ""]

        if self.suno_lyrics_prompt:
            lines += ["## Suno Lyrics Prompt", "", f"```\n{self.suno_lyrics_prompt}\n```", ""]

        return "\n".join(lines).strip() + "\n"