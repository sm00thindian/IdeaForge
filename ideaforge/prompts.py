"""LLM prompt templates for meeting and creative processing modes."""

from __future__ import annotations

import re
from typing import Literal

Mode = Literal["meeting", "creative", "auto"]

SPEAKER_LABEL_PATTERN = re.compile(r"\[SPEAKER_\d+\]", re.IGNORECASE)


def transcript_has_speaker_labels(transcript: str) -> bool:
    return bool(SPEAKER_LABEL_PATTERN.search(transcript))


MEETING_SYSTEM = """You are a senior chief-of-staff and meeting analyst. You transform messy voice \
transcripts into executive-grade meeting notes that are precise, actionable, and grounded in evidence.

Core principles:
- Ground every claim in the transcript. Never invent participants, decisions, or deadlines.
- Distinguish firm decisions from proposals, brainstorming, and unresolved debate.
- Extract both explicit commitments ("I will send the deck Friday") and implicit ones ("someone should \
reach out to legal" → action item with inferred owner if clear from context).
- When speaker labels ([SPEAKER_00], etc.) are present, infer real names or roles from conversation \
evidence (self-introductions, direct address, context). Populate speaker_identities with your best \
guess and confidence for each label.
- Use inferred names everywhere people are referenced: speakers, action_items.who, decisions.made_by, \
and follow_ups.owner. Never use raw SPEAKER_XX in those fields when speaker_identities has a \
medium- or high-confidence guess — use the inferred_name instead (optionally with label in parens).
- Only use raw SPEAKER_XX or 'TBD' when confidence is low or unknown.
- When no speaker labels exist, use "Unattributed" or role descriptions only if clearly inferable \
(e.g., "the client", "project lead") — never guess personal names without evidence.
- Prefer completeness over brevity for action items: a missed commitment is worse than a redundant one.

Output valid JSON only — no markdown fences, no commentary before or after the JSON."""

MEETING_USER_TEMPLATE = """Analyze this voice transcript and produce structured meeting notes.

Speaker labels detected: {speaker_context}

Return a JSON object with exactly these keys:
{{
  "title": "concise, specific meeting title (not generic like 'Meeting Notes')",
  "date": "YYYY-MM-DD if inferable from content or filename context, else empty string",
  "meeting_type": "sync|planning|1:1|brainstorm|standup|review|interview|voice_memo|other",
  "executive_summary": "3-5 sentences: purpose, outcome, and what matters most going forward",
  "topics": ["main agenda topics discussed, in order"],
  "speaker_identities": [
    {{
      "speaker_id": "SPEAKER_XX — pyannote label from transcript",
      "inferred_name": "best-guess real name, role, or descriptive label (e.g. 'Project lead')",
      "confidence": "high|medium|low|unknown — high only with direct evidence (name stated or used)",
      "rationale": "brief quote or context supporting the guess, or why unknown"
    }}
  ],
  "speakers": [
    {{
      "speaker": "inferred name or role; include (SPEAKER_XX) when labels exist",
      "summary": "what this person contributed, their stance, and any commitments they made",
      "key_quotes": ["verbatim quotes that capture decisions or strong positions, max 2"]
    }}
  ],
  "key_points": [
    "substantive discussion points — facts, proposals, context, not action items"
  ],
  "action_items": [
    {{
      "who": "inferred_name from speaker_identities (e.g. 'Alex' or 'Project lead'); never raw SPEAKER_XX when a medium/high-confidence identity exists; 'TBD' only if truly unclear",
      "what": "specific, testable deliverable (not vague 'follow up')",
      "when": "deadline if stated, reasonably inferred ('end of week'), or null",
      "priority": "high|medium|low — high if blocking, time-sensitive, or executive-requested",
      "confidence": "explicit|inferred — explicit if directly committed, inferred if implied",
      "source_quote": "short verbatim quote supporting this action, or null",
      "blocked_by": "dependency or blocker if mentioned, else null"
    }}
  ],
  "decisions": [
    {{
      "decision": "what was decided or agreed",
      "rationale": "why, if discussed",
      "made_by": "inferred_name from speaker_identities, not raw SPEAKER_XX when identity is known"
    }}
  ],
  "open_questions": [
    "unresolved questions that need answers — not action items"
  ],
  "follow_ups": [
    {{
      "topic": "what needs revisiting in a future session",
      "owner": "inferred_name from speaker_identities, not raw SPEAKER_XX when identity is known",
      "by_when": "timing if mentioned, else null",
      "context": "why this needs follow-up"
    }}
  ],
  "risks_blockers": [
    "risks, blockers, concerns, or dependencies raised in the discussion"
  ]
}}

Extraction rules:
1. Action items: capture every commitment, offer, and request — including "I'll...", "we need to...", \
"can you...", "let's...", "someone should...". De-duplicate only exact repeats.
2. Decisions: include only items with consensus or clear approval. Tag proposals still under debate as \
open_questions, not decisions.
3. Follow-ups vs action items: action items have a deliverable; follow-ups are topics to revisit without \
a clear deliverable yet.
4. Open questions: things explicitly unanswered or punted ("we'll figure that out later").
5. Priority: high = blocking release/deadline/executive ask; medium = important but not urgent; \
low = nice-to-have.
6. Speaker identities: for every distinct [SPEAKER_XX] in the transcript, add one speaker_identities \
entry. Prefer real names when someone says "I'm Alex" or "Hey Sarah"; use roles ("Interviewer", \
"Client") when names are never mentioned; use unknown + SPEAKER_XX when evidence is insufficient.
7. Action item owners: map each commitment to the speaking [SPEAKER_XX], look up that label in \
speaker_identities, and set who to the inferred_name (e.g. "Husband/partner", not "SPEAKER_02"). \
Apply the same mapping for decisions.made_by and follow_ups.owner.
8. If this is a solo voice memo with no meeting structure, set meeting_type to "voice_memo" and still \
extract any tasks, ideas, or decisions the speaker mentions.

Transcript:
{transcript}"""

CREATIVE_SYSTEM = """You are a creative collaborator who transforms voice memos into song ideas, \
lyrics fragments, and Suno v5.5-ready prompts. You capture the emotional core and musical potential \
of hummed ideas, porch reflections, and lyrical fragments. Output valid JSON only."""

CREATIVE_USER_TEMPLATE = """Analyze this voice memo transcript for creative musical potential.

Return a JSON object with exactly these keys:
{{
  "title": "working title for the piece",
  "date": "YYYY-MM-DD if inferable, else empty string",
  "creative_summary": "2-3 sentences capturing the creative essence",
  "themes": ["emotional or narrative themes"],
  "sparks": [
    {{
      "title": "idea name",
      "description": "what makes this interesting",
      "genre": "suggested genre or null",
      "mood": "emotional mood or null",
      "lyrics_snippet": "polished lyrics fragment from the memo or null",
      "suno_prompt": "concise Suno style prompt for this spark or null"
    }}
  ],
  "lyrics_draft": "expanded lyrics draft if enough material, else null",
  "suno_style_prompt": "full Suno v5.5 style prompt (genre, instruments, tempo, mood)",
  "suno_lyrics_prompt": "Suno lyrics section with [Verse], [Chorus] structure if applicable"
}}

Rules:
- Honor the speaker's original words — polish, don't replace their voice.
- If they hummed or described a melody, note it in descriptions.
- Suno prompts should be specific: genre, BPM feel, instrumentation, vocal style.
- If content is clearly a meeting (not creative), still extract any creative sparks but note the mismatch.

Transcript:
{transcript}"""

AUTO_SYSTEM = """You are IdeaForge's routing analyst. First classify the transcript, then produce \
the appropriate structured output. Output valid JSON only."""

AUTO_USER_TEMPLATE = """Classify this transcript and produce structured output.

Step 1: Set "mode" to "meeting" or "creative" based on content.
Step 2: If meeting, include these keys:
  title, date, meeting_type, executive_summary, topics, speaker_identities, speakers, key_points,
  action_items, decisions, open_questions, follow_ups, risks_blockers
Step 3: If creative, include these keys:
  title, date, creative_summary, themes, sparks, lyrics_draft, suno_style_prompt, suno_lyrics_prompt

Always include "mode" as the first key in the JSON object.

Transcript:
{transcript}"""


def build_prompt(
    mode: Mode,
    transcript: str,
    max_chars: int = 24_000,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the given mode."""
    clipped = transcript[:max_chars]
    if mode == "meeting":
        speaker_context = (
            "yes — infer real names or roles for each [SPEAKER_XX] from conversation evidence; "
            "populate speaker_identities and use inferred names in notes when confident"
            if transcript_has_speaker_labels(clipped)
            else "no — speakers are not labeled; use roles or 'Unattributed'"
        )
        return MEETING_SYSTEM, MEETING_USER_TEMPLATE.format(
            transcript=clipped,
            speaker_context=speaker_context,
        )
    if mode == "creative":
        return CREATIVE_SYSTEM, CREATIVE_USER_TEMPLATE.format(transcript=clipped)
    return AUTO_SYSTEM, AUTO_USER_TEMPLATE.format(transcript=clipped)