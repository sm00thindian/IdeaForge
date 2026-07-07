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
    notes: Optional[str] = None
    status: Optional[str] = "Open"


@dataclass
class DiscussionTopic:
    title: str
    points: List[str] = field(default_factory=list)


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
class SpeakerIdentity:
    speaker_id: str
    inferred_name: str
    confidence: str  # high | medium | low | unknown
    rationale: Optional[str] = None


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
    time: Optional[str] = None
    platform: Optional[str] = None
    attendees: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    discussion_topics: List[DiscussionTopic] = field(default_factory=list)
    preparation_notes: List[str] = field(default_factory=list)
    speaker_identities: List[SpeakerIdentity] = field(default_factory=list)
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
        lines: List[str] = []
        recording_date = self.metadata.get("recording_date")
        recording_source = self.metadata.get("recording_date_source")
        if recording_date:
            lines.extend([
                "---",
                f"date: {recording_date}",
                f"recording_date_source: {recording_source or 'unknown'}",
                "---",
                "",
            ])
        lines.extend([
            f"# Meeting Minutes: {self.title}",
            "",
            f"**Date:** {self.date or 'TBD'}",
            f"**Time:** {self.time or 'TBD'}",
            f"**Platform:** {self.platform or 'TBD'}",
            f"**Attendees:** {self.attendees or 'See transcript for participants'}",
        ])
        if recording_source:
            lines.append(f"**Recording date source:** {recording_source}")
        lines += ["", "## Executive Summary", "", self.executive_summary, ""]

        lines += ["## Action Items", ""]
        if self.action_items:
            lines.append(
                "| # | Action Item | Owner | Due Date / Timeframe | "
                "Notes / Context / Dependencies | Status |"
            )
            lines.append(
                "|---|-------------|-------|----------------------|"
                "--------------------------------|--------|"
            )
            for index, item in enumerate(self.action_items, start=1):
                notes_parts = [
                    part
                    for part in (
                        item.notes,
                        item.blocked_by,
                        item.source_quote,
                    )
                    if part
                ]
                notes = " — ".join(notes_parts) if notes_parts else "—"
                lines.append(
                    f"| {index} | {item.what} | {item.who} | "
                    f"{item.when or 'TBD'} | {notes} | {item.status or 'Open'} |"
                )
        else:
            lines.append(
                "No explicit action items were captured in the transcript."
            )
        lines.append("")

        if self.decisions:
            lines += ["## Key Decisions", ""]
            for dec in self.decisions:
                if isinstance(dec, Decision):
                    bullet = dec.decision
                    if dec.rationale:
                        bullet = f"{bullet} ({dec.rationale})"
                    if dec.made_by:
                        bullet = f"{bullet} — {dec.made_by}"
                    lines.append(f"- {bullet}")
                else:
                    lines.append(f"- {dec}")
            lines.append("")

        discussion = self.discussion_topics
        if not discussion and (self.topics or self.key_points):
            discussion = [
                DiscussionTopic(title=topic, points=[])
                for topic in self.topics
            ]
            if self.key_points and discussion:
                discussion[0].points.extend(self.key_points)
            elif self.key_points:
                discussion = [DiscussionTopic(title="Discussion", points=self.key_points)]

        if discussion:
            lines += ["## Discussion Summary", ""]
            for topic in discussion:
                lines.append(f"### {topic.title}")
                for point in topic.points:
                    lines.append(f"- {point}")
                lines.append("")

        parking_lot: List[str] = list(self.open_questions)
        for fu in self.follow_ups:
            if isinstance(fu, FollowUp):
                label = fu.topic
                if fu.owner:
                    label = f"{label} ({fu.owner})"
                if fu.by_when:
                    label = f"{label} — by {fu.by_when}"
                if fu.context:
                    label = f"{label}: {fu.context}"
                parking_lot.append(label)
            else:
                parking_lot.append(str(fu))

        if parking_lot:
            lines += ["## Open Questions / Parking Lot Items", ""]
            for item in parking_lot:
                lines.append(f"- {item}")
            lines.append("")

        if self.risks_blockers:
            if not discussion:
                lines += ["## Discussion Summary", ""]
            lines += ["### Risks, Blockers, and Implications", ""]
            for risk in self.risks_blockers:
                lines.append(f"- {risk}")
            lines.append("")

        if self.preparation_notes:
            lines += ["## Preparation Notes (for the minutes author)", ""]
            for note in self.preparation_notes:
                lines.append(f"- {note}")
            lines.append("")

        lines.append("**End of Minutes**")
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