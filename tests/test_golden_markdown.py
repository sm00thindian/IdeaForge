"""Golden-file contracts for meeting and song markdown rendering.

If these fail after an intentional format change, update files under
``tests/goldens/`` deliberately (do not silently loosen asserts).
"""

from pathlib import Path

from ideaforge.schema import (
    ActionItem,
    CreativeOutput,
    CreativeSpark,
    Decision,
    DiscussionTopic,
    FollowUp,
    MeetingNotes,
)

GOLDENS = Path(__file__).parent / "goldens"


def test_meeting_notes_golden_markdown():
    notes = MeetingNotes(
        title="Sprint Planning",
        date="2026-06-27",
        time="10:00 AM ET",
        platform="Zoom",
        attendees="Alex (Engineering), Jordan (PM)",
        meeting_type="planning",
        executive_summary="Team aligned on Q3 priorities.",
        discussion_topics=[
            DiscussionTopic(title="Timeline", points=["Backend refactor is priority"]),
        ],
        action_items=[
            ActionItem(
                who="Alex",
                what="Update roadmap",
                when="Friday",
                notes="Supports Q3 release planning",
                status="Open",
            )
        ],
        decisions=[
            Decision(decision="Delay launch to August", rationale="Backend not ready")
        ],
        follow_ups=[
            FollowUp(topic="Capacity planning", owner="Alex", by_when="next sync")
        ],
        risks_blockers=["Hiring delay on backend team"],
        preparation_notes=["[Unclear in transcript: exact launch date]"],
        metadata={
            "recording_date": "2026-06-27",
            "recording_date_source": "filename",
            "session_stem": "R2026-06-27-10-00-00",
            "llm_backend": "grok",
            "llm_model": "grok-4.3",
        },
    )
    expected = (GOLDENS / "meeting_notes.md").read_text(encoding="utf-8")
    assert notes.to_markdown() == expected


def test_creative_song_golden_markdown():
    output = CreativeOutput(
        title="Porch Song",
        date="2026-06-27",
        creative_summary="A reflective acoustic piece.",
        themes=["nostalgia", "summer"],
        chorus_hook="Dancing in the summer light",
        suno_style_prompt="acoustic folk, 85 BPM, warm and intimate",
        suno_lyrics_prompt="[Verse 1]\nFireflies glow\n[Chorus]\nSummer night",
        udio_prompt="Porch memories, folk, mellow, warm",
        udio_lyrics="[Verse 1]\nFireflies glow\n[Chorus]\nSummer night",
        sparks=[
            CreativeSpark(
                title="Verse idea",
                description="Opening about fireflies",
                genre="folk",
                mood="wistful",
                suno_prompt="acoustic folk, gentle fingerpicking, warm male vocal",
            )
        ],
    )
    expected = (GOLDENS / "creative_song.md").read_text(encoding="utf-8")
    assert output.to_markdown() == expected
