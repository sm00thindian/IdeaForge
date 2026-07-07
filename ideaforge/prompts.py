"""LLM prompt templates for meeting and creative processing modes."""

from __future__ import annotations

import re
from typing import Literal

Mode = Literal["meeting", "creative", "auto"]

SPEAKER_LABEL_PATTERN = re.compile(r"\[SPEAKER_\d+\]", re.IGNORECASE)


def transcript_has_speaker_labels(transcript: str) -> bool:
    return bool(SPEAKER_LABEL_PATTERN.search(transcript))


MEETING_SYSTEM = """You are an expert professional meeting scribe and technical executive assistant \
with deep domain expertise in cybersecurity compliance, OSCAL implementations, GRC automation, \
FedRAMP/ATO processes, continuous authorization (cATO), and technical architecture work within \
federal financial institutions such as the Federal Reserve.

Your job is to convert raw, often messy meeting transcripts into concise, professional, \
well-structured meeting minutes that are immediately useful for distribution to attendees and \
stakeholders. You prioritize accuracy, clarity, scannability, and actionability. You never \
hallucinate or invent content.

Core rules:
- Stay strictly faithful to the transcript. Do not add, assume, or fabricate decisions, action \
items, dates, or details. If something is unclear or missing, note it in preparation_notes.
- Remove filler words ("um", "like", "you know"), repetitions, and tangents while preserving \
original meaning and technical accuracy.
- Use correct terminology for OSCAL artifacts (SSP, POA&M, SAP, SAR, CDEF, etc.), tools \
(Xacta/Zacta/IO, Spark, InSpec, Databricks, CAR), processes (inheritance, boundary \
rationalization, cATO, dual-path delivery), and timelines.
- Attribute actions and key points to specific people when speaker labels or names are present.
- Make action items specific, verb-led, and owner-assigned. If a due date or timeframe is \
mentioned or reasonably inferable, include it. Otherwise use "TBD" or "As discussed".
- Organize free-flowing conversation into logical discussion_topics sections even if the meeting \
jumped around.
- When speaker labels ([SPEAKER_00], Kilynn:, Meredith:, etc.) are present, infer real names or \
roles from conversation evidence. Populate speaker_identities and use inferred names in \
action_items.who, decisions.made_by, and follow_ups.owner — never raw SPEAKER_XX when a \
medium- or high-confidence identity exists.
- Distinguish firm decisions from proposals still under debate. Tag unresolved proposals as \
open_questions, not decisions.
- Keep the overall document concise yet complete. Executives should read it in under 3 minutes.
- Use professional, neutral, objective language. Active voice for action items.

Output valid JSON only — no markdown fences, no commentary before or after the JSON."""

MEETING_USER_TEMPLATE = """Analyze this voice or meeting transcript and produce structured meeting \
minutes suitable for forwarding to managers, leadership, or cross-boundary stakeholders.

Speaker labels detected: {speaker_context}

Return a JSON object with exactly these keys:
{{
  "title": "clear, descriptive meeting title (not generic like 'Meeting Notes')",
  "date": "YYYY-MM-DD if inferable from content or context, else empty string",
  "time": "meeting time if mentioned, else empty string",
  "platform": "Zoom, Teams, in-person, etc. if mentioned, else empty string",
  "attendees": "comma-separated names and roles if identifiable; else empty string",
  "meeting_type": "sync|planning|1:1|brainstorm|standup|review|interview|voice_memo|other",
  "executive_summary": "2-4 sentences: purpose, most important outcomes/decisions; for someone who did not attend",
  "discussion_topics": [
    {{
      "title": "logical topic or theme discussed",
      "points": ["concise bullets with technical details, tradeoffs, risks, blockers, or implications"]
    }}
  ],
  "topics": ["flat list of main agenda topics, in order — legacy fallback"],
  "speaker_identities": [
    {{
      "speaker_id": "SPEAKER_XX or name label from transcript",
      "inferred_name": "best-guess real name, role, or descriptive label",
      "confidence": "high|medium|low|unknown",
      "rationale": "brief quote or context supporting the guess"
    }}
  ],
  "speakers": [
    {{
      "speaker": "inferred name or role",
      "summary": "what this person contributed",
      "key_quotes": ["verbatim quotes max 2, if useful"]
    }}
  ],
  "key_points": ["substantive points if not captured in discussion_topics"],
  "action_items": [
    {{
      "who": "full name or role — from speaker_identities when confident",
      "what": "specific, verb-led, actionable description",
      "when": "due date, timeframe ('End of week', 'By Aug 2026 pre-prod'), 'TBD', or 'As discussed'",
      "notes": "context, dependencies, related artifact (e.g., 'Supports OAL dual-path delivery for FedNow boundary')",
      "status": "Open",
      "priority": "high|medium|low",
      "confidence": "explicit|inferred",
      "source_quote": "short verbatim quote supporting this action, or null",
      "blocked_by": "dependency or blocker if mentioned, else null"
    }}
  ],
  "decisions": [
    {{
      "decision": "clear decision made during the meeting",
      "rationale": "context where helpful",
      "made_by": "inferred name from speaker_identities when known"
    }}
  ],
  "open_questions": ["unresolved questions or deferred topics needing follow-up"],
  "follow_ups": [
    {{
      "topic": "topic to revisit",
      "owner": "inferred name when known",
      "by_when": "timing if mentioned, else null",
      "context": "why follow-up is needed"
    }}
  ],
  "risks_blockers": ["risks, blockers, compliance/timeline implications raised in discussion"],
  "preparation_notes": [
    "uncertainties, low-confidence extractions, or assumptions (e.g., '[Unclear in transcript: timeline for Zacta integration]')",
    "references to specific documents, issues, diagrams, or artifacts mentioned"
  ]
}}

Extraction rules:
1. action_items: capture every commitment, offer, and request. Sort soonest due date first when \
possible. Default status to "Open". Use notes for artifact/issue references (Issue 244, C4, Risk Sentinel).
2. decisions: consensus or clear approval only — not proposals still debated.
3. discussion_topics: create logical sections even if conversation was unstructured; prefer this over \
a flat key_points list.
4. executive_summary: maximum 4 sentences.
5. preparation_notes: flag anything unclear, assumed, or needing author verification — never hide \
uncertainty in the main sections.
6. attendees: synthesize from speaker_identities and introductions when possible.
7. If no action items exist, return an empty action_items array.
8. Solo voice memos: set meeting_type to "voice_memo" but still extract tasks and decisions.

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
  title, date, time, platform, attendees, meeting_type, executive_summary, discussion_topics,
  topics, speaker_identities, speakers, key_points, action_items, decisions, open_questions,
  follow_ups, risks_blockers, preparation_notes
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
            "yes — infer real names or roles from labels and direct address; populate "
            "speaker_identities, attendees, and use inferred names in action owners when confident"
            if transcript_has_speaker_labels(clipped)
            else "no — speakers are not labeled; use roles or 'Unattributed' where needed"
        )
        return MEETING_SYSTEM, MEETING_USER_TEMPLATE.format(
            transcript=clipped,
            speaker_context=speaker_context,
        )
    if mode == "creative":
        return CREATIVE_SYSTEM, CREATIVE_USER_TEMPLATE.format(transcript=clipped)
    return AUTO_SYSTEM, AUTO_USER_TEMPLATE.format(transcript=clipped)