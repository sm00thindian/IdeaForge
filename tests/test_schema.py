"""Tests for structured output schemas."""

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


def test_meeting_notes_markdown():
    notes = MeetingNotes(
        title="Sprint Planning",
        date="2026-06-27",
        time="10:00 AM ET",
        platform="Zoom",
        attendees="Alex (Engineering), Jordan (PM)",
        meeting_type="planning",
        executive_summary="Team aligned on Q3 priorities.",
        discussion_topics=[
            DiscussionTopic(
                title="Timeline",
                points=["Backend refactor is priority"],
            )
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
        decisions=[Decision(decision="Delay launch to August", rationale="Backend not ready")],
        follow_ups=[FollowUp(topic="Capacity planning", owner="Alex", by_when="next sync")],
        risks_blockers=["Hiring delay on backend team"],
        preparation_notes=["[Unclear in transcript: exact launch date]"],
    )
    md = notes.to_markdown()
    assert "# Meeting Minutes: Sprint Planning" in md
    assert "Alex" in md
    assert "Delay launch to August" in md
    assert "## Action Items" in md
    assert "| 1 | Update roadmap | Alex |" in md
    assert "Preparation Notes" in md
    assert "**End of Minutes**" in md


def test_empty_action_items_message():
    notes = MeetingNotes(
        title="Team Sync",
        date="2026-06-27",
        executive_summary="Quick alignment on priorities.",
    )
    md = notes.to_markdown()
    assert "No explicit action items were captured in the transcript." in md


def test_creative_output_json_roundtrip():
    output = CreativeOutput(
        title="Porch Song",
        date="2026-06-27",
        creative_summary="A reflective acoustic piece.",
        themes=["nostalgia", "summer"],
        sparks=[
            CreativeSpark(
                title="Verse idea",
                description="Opening about fireflies",
                genre="folk",
                mood="wistful",
                suno_prompt="acoustic folk, gentle fingerpicking, warm male vocal",
            )
        ],
        suno_style_prompt="Acoustic folk, 85 BPM, warm and intimate",
    )
    data = output.to_dict()
    assert data["title"] == "Porch Song"
    assert len(data["sparks"]) == 1
    assert "Suno Style Prompt" in output.to_markdown()