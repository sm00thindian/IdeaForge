"""Structured output schemas for meeting notes and creative modes."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Match


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


_SPEAKER_ID_RE = re.compile(r"SPEAKER[_\s]?\d+", re.IGNORECASE)
_MEETING_TYPE_LABELS = {
    "standup": "Standup",
    "sync": "Sync",
    "planning": "Planning",
    "1:1": "1:1",
    "brainstorm": "Brainstorm",
    "review": "Review",
    "interview": "Interview",
    "voice_memo": "Voice memo",
    "other": "Meeting",
}


def _shorten(text: str, max_len: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or cleaned[: max_len - 1]).rstrip(".,;:") + "…"


def _is_unknown_name(name: str) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered:
        return True
    if lowered.startswith("unknown"):
        return True
    if "could not" in lowered or "not inferred" in lowered:
        return True
    if _SPEAKER_ID_RE.fullmatch(name.strip().replace(" ", "_")):
        return True
    return False


def speaker_display_map(
    identities: List[SpeakerIdentity],
) -> Dict[str, str]:
    """Map SPEAKER_xx / ids to human-facing display names."""
    mapping: Dict[str, str] = {}
    letter_i = 0
    for ident in identities:
        sid = (ident.speaker_id or "").strip()
        if not sid:
            continue
        conf = (ident.confidence or "").strip().lower()
        name = (ident.inferred_name or "").strip()
        if conf in ("high", "medium") and not _is_unknown_name(name):
            display = name
        elif not _is_unknown_name(name) and conf not in ("unknown",):
            display = name
        else:
            display = f"Participant {chr(ord('A') + letter_i)}"
            letter_i += 1
        mapping[sid] = display
        # Normalize SPEAKER_00 / SPEAKER 00 variants
        m = re.search(r"(\d+)", sid)
        if m:
            mapping[f"SPEAKER_{int(m.group(1)):02d}"] = display
            mapping[f"SPEAKER_{int(m.group(1))}"] = display
    return mapping


def apply_speaker_display(text: str, mapping: Dict[str, str]) -> str:
    """Replace SPEAKER_xx tokens in free text with display names."""
    if not text or not mapping:
        return text
    result = text
    # Longest keys first to avoid partial overwrites
    for sid, name in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
        result = re.sub(re.escape(sid), name, result, flags=re.IGNORECASE)
    # Residual SPEAKER_N → Participant N style
    def _residual(match: Match[str]) -> str:
        num = match.group(1)
        key = f"SPEAKER_{int(num):02d}"
        if key in mapping:
            return mapping[key]
        return f"Participant {num}"

    result = re.sub(r"SPEAKER[_\s]?(\d+)", _residual, result, flags=re.IGNORECASE)
    return result


def meeting_title_line(*, title: str, meeting_type: Optional[str]) -> str:
    clean = (title or "Untitled").strip()
    # Drop redundant prefix if model still emits it
    clean = re.sub(r"^meeting minutes:\s*", "", clean, flags=re.IGNORECASE)
    type_key = (meeting_type or "").strip().lower()
    label = _MEETING_TYPE_LABELS.get(type_key)
    if label and not clean.lower().startswith(label.lower()):
        return f"# {label} · {clean}"
    return f"# {clean}"


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

    def _display(self, text: Optional[str], mapping: Dict[str, str]) -> str:
        return apply_speaker_display(text or "", mapping)

    def to_markdown(self) -> str:
        """Render human-facing minutes (exec skim order; no TBD spam)."""
        mapping = speaker_display_map(self.speaker_identities)
        lines: List[str] = []

        # Light frontmatter for tools; heavy metadata moves to footer.
        recording_date = self.metadata.get("recording_date")
        if recording_date:
            lines.extend(["---", f"date: {recording_date}", "---", ""])

        lines.append(
            meeting_title_line(title=self.title, meeting_type=self.meeting_type)
        )
        lines.append("")

        # Header: only non-empty facts (no TBD clutter).
        header_bits: List[str] = []
        date_val = (self.date or recording_date or "").strip()
        if date_val and date_val.upper() != "TBD":
            header_bits.append(f"**Date:** {date_val}")
        if self.time and self.time.strip().upper() not in ("", "TBD"):
            header_bits.append(f"**Time:** {self.time.strip()}")
        if self.platform and self.platform.strip().upper() not in ("", "TBD"):
            header_bits.append(f"**Platform:** {self.platform.strip()}")
        if self.attendees and self.attendees.strip():
            att = self._display(self.attendees.strip(), mapping)
            if att.lower() not in (
                "see transcript for participants",
                "see transcript",
            ):
                header_bits.append(f"**Attendees:** {att}")
        if header_bits:
            lines.extend(header_bits)
            lines.append("")

        # 1) Snapshot
        summary = self._display(self.executive_summary, mapping).strip()
        if summary:
            lines += ["## Snapshot", "", summary, ""]

        # 2) Decisions
        lines += ["## Decisions", ""]
        if self.decisions:
            for dec in self.decisions:
                if isinstance(dec, Decision):
                    bullet = self._display(dec.decision, mapping)
                    if dec.rationale:
                        bullet = f"{bullet} ({self._display(dec.rationale, mapping)})"
                    if dec.made_by:
                        bullet = f"{bullet} — {self._display(dec.made_by, mapping)}"
                    lines.append(f"- {bullet}")
                else:
                    lines.append(f"- {self._display(str(dec), mapping)}")
        else:
            lines.append("_None recorded._")
        lines.append("")

        # 3) Action items (scannable; quotes stay out of the table)
        lines += ["## Action items", ""]
        if self.action_items:
            lines.append("| # | Action | Owner | Due | P | Context |")
            lines.append("|---|--------|-------|-----|---|---------|")
            for index, item in enumerate(self.action_items, start=1):
                who = self._display(item.who or "TBD", mapping)
                what = self._display(item.what or "", mapping)
                when = (item.when or "TBD").strip() or "TBD"
                priority = (item.priority or "—")[:1].upper() if item.priority else "—"
                if item.priority and item.priority.lower() in ("high", "medium", "low"):
                    priority = {"high": "H", "medium": "M", "low": "L"}[
                        item.priority.lower()
                    ]
                context_parts = [
                    p
                    for p in (item.notes, item.blocked_by)
                    if p and str(p).strip()
                ]
                context = _shorten(
                    self._display(" · ".join(context_parts), mapping), 100
                ) if context_parts else "—"
                if item.confidence and item.confidence.lower() == "inferred":
                    what = f"{what}*"
                lines.append(
                    f"| {index} | {what} | {who} | {when} | {priority} | {context} |"
                )
            if any(
                (item.confidence or "").lower() == "inferred"
                for item in self.action_items
            ):
                lines.append("")
                lines.append("\\* Inferred from discussion (not an explicit commitment).")
        else:
            lines.append("No explicit action items captured.")
        lines.append("")

        # 4) Risks
        if self.risks_blockers:
            lines += ["## Risks & blockers", ""]
            for risk in self.risks_blockers:
                lines.append(f"- {self._display(risk, mapping)}")
            lines.append("")

        # 5) Discussion
        discussion = self.discussion_topics
        if not discussion and (self.topics or self.key_points):
            discussion = [
                DiscussionTopic(title=topic, points=[]) for topic in self.topics
            ]
            if self.key_points and discussion:
                discussion[0].points.extend(self.key_points)
            elif self.key_points:
                discussion = [
                    DiscussionTopic(title="Discussion", points=list(self.key_points))
                ]

        if discussion:
            lines += ["## Discussion", ""]
            for topic in discussion:
                lines.append(f"### {self._display(topic.title, mapping)}")
                for point in topic.points:
                    lines.append(f"- {self._display(point, mapping)}")
                lines.append("")

        # 6) Open questions / follow-ups
        parking: List[str] = [
            self._display(q, mapping) for q in self.open_questions if q
        ]
        for fu in self.follow_ups:
            if isinstance(fu, FollowUp):
                label = self._display(fu.topic, mapping)
                if fu.owner:
                    label = f"{label} ({self._display(fu.owner, mapping)})"
                if fu.by_when:
                    label = f"{label} — by {fu.by_when}"
                if fu.context:
                    label = f"{label}: {self._display(fu.context, mapping)}"
                parking.append(label)
            else:
                parking.append(self._display(str(fu), mapping))
        if parking:
            lines += ["## Open questions", ""]
            for item in parking:
                lines.append(f"- {item}")
            lines.append("")

        # 7) Participants (from speaker_identities)
        if self.speaker_identities:
            lines += ["## Participants", ""]
            lines.append("| Label | Name | Confidence |")
            lines.append("|-------|------|------------|")
            for ident in self.speaker_identities:
                sid = ident.speaker_id or "—"
                display = mapping.get(sid, ident.inferred_name or sid)
                conf = ident.confidence or "unknown"
                lines.append(f"| {sid} | {display} | {conf} |")
            lines.append("")

        # 8) Prep notes (author-facing)
        if self.preparation_notes:
            lines += ["## Notes for author", ""]
            for note in self.preparation_notes:
                lines.append(f"- {self._display(note, mapping)}")
            lines.append("")

        # Footer metadata
        footer = self._footer_bits()
        if footer:
            lines += ["---", "", " · ".join(footer), ""]

        return "\n".join(lines).strip() + "\n"

    def _footer_bits(self) -> List[str]:
        bits: List[str] = []
        meta = self.metadata or {}
        rec_date = meta.get("recording_date")
        rec_src = meta.get("recording_date_source")
        if rec_date:
            if rec_src:
                bits.append(f"Recording date: {rec_date} ({rec_src})")
            else:
                bits.append(f"Recording date: {rec_date}")
        stem = meta.get("session_stem") or meta.get("source_transcript")
        if stem:
            bits.append(f"Session: {stem}")
        model = meta.get("llm_model")
        backend = meta.get("llm_backend")
        if model or backend:
            bits.append(f"Model: {backend or '?'} · {model or '?'}")
        return bits


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
    """Structured creative output — lyrics, song ideas, Suno/Udio prompts."""

    title: str
    date: str
    creative_summary: str
    themes: List[str] = field(default_factory=list)
    sparks: List[CreativeSpark] = field(default_factory=list)
    intent: str = "song_idea"
    raw_lyric_fragments: List[str] = field(default_factory=list)
    detected_style: Optional[str] = None
    rhyme_scheme: Optional[str] = None
    applied_style: Optional[str] = None
    style_variation_index: Optional[int] = None
    chorus_hook: Optional[str] = None
    chorus_variants: List[str] = field(default_factory=list)
    lyrics_draft: Optional[str] = None
    suno_style_prompt: Optional[str] = None
    suno_lyrics_prompt: Optional[str] = None
    udio_prompt: Optional[str] = None
    udio_lyrics: Optional[str] = None
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

        if self.detected_style or self.applied_style or self.rhyme_scheme:
            lines += ["## Style", ""]
            if self.detected_style:
                lines.append(f"- **From memo:** {self.detected_style}")
            if self.applied_style:
                lines.append(f"- **Applied:** {self.applied_style}")
            if self.rhyme_scheme:
                lines.append(f"- **Rhyme scheme:** {self.rhyme_scheme}")
            lines.append("")

        if self.themes:
            lines += ["## Themes", ""]
            for theme in self.themes:
                lines.append(f"- {theme}")
            lines.append("")

        if self.chorus_hook:
            lines += ["## Chorus Hook", "", f"> {self.chorus_hook}", ""]

        if self.chorus_variants:
            lines += ["## Chorus Variants", ""]
            for index, variant in enumerate(self.chorus_variants, start=1):
                lines.append(f"{index}. {variant}")
            lines.append("")

        if self.raw_lyric_fragments:
            lines += ["## Raw Fragments", ""]
            for fragment in self.raw_lyric_fragments:
                lines.append(f"- {fragment}")
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
            lines += [
                "## Suno v5.5 Style",
                "",
                "Copy into Suno **Style of Music**:",
                "",
                f"```\n{self.suno_style_prompt}\n```",
                "",
            ]

        if self.suno_lyrics_prompt:
            lines += [
                "## Suno v5.5 Lyrics",
                "",
                "Copy into Suno **Lyrics**:",
                "",
                f"```\n{self.suno_lyrics_prompt}\n```",
                "",
            ]

        if self.udio_prompt:
            lines += [
                "## Udio Prompt",
                "",
                "Copy into Udio **Describe Your Song**:",
                "",
                f"```\n{self.udio_prompt}\n```",
                "",
            ]

        if self.udio_lyrics:
            lines += [
                "## Udio Lyrics",
                "",
                "Copy into Udio **Custom Lyrics**:",
                "",
                f"```\n{self.udio_lyrics}\n```",
                "",
            ]

        return "\n".join(lines).strip() + "\n"
