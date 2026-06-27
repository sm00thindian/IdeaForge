"""Tests for structured output schemas."""

from ideaforge.schema import (
    ActionItem,
    CreativeOutput,
    CreativeSpark,
    Decision,
    FollowUp,
    MeetingNotes,
    SpeakerContribution,
)


def test_meeting_notes_markdown():
    notes = MeetingNotes(
        title="Sprint Planning",
        date="2026-06-27",
        meeting_type="planning",
        executive_summary="Team aligned on Q3 priorities.",
        topics=["Timeline", "Backend refactor"],
        speakers=[
            SpeakerContribution(
                speaker="SPEAKER_00",
                summary="Proposed timeline changes",
                key_quotes=["We need two more weeks"],
            )
        ],
        key_points=["Backend refactor is priority"],
        action_items=[
            ActionItem(
                who="Alex",
                what="Update roadmap",
                when="Friday",
                priority="high",
                confidence="explicit",
                source_quote="I'll update the roadmap by Friday",
            )
        ],
        decisions=[Decision(decision="Delay launch to August", rationale="Backend not ready")],
        follow_ups=[FollowUp(topic="Capacity planning", owner="Alex", by_when="next sync")],
        risks_blockers=["Hiring delay on backend team"],
    )
    md = notes.to_markdown()
    assert "# Sprint Planning" in md
    assert "SPEAKER_00" in md
    assert "Alex" in md
    assert "Delay launch to August" in md
    assert "Risks & Blockers" in md
    assert "explicit" in md


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