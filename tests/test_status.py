"""Tests for pipeline status reporting."""

from ideaforge.pipeline import PipelineStages
from ideaforge.status import (
    STATE_COMPLETE,
    STATE_PROCESSING,
    STEP_ACTIVE,
    STEP_DONE,
    StatusReporter,
    build_step_plan,
    load_status,
    menu_bar_title,
)


def test_build_step_plan_includes_pipeline_stages():
    stages = PipelineStages(copy=True, transcribe=True, diarize=True, llm=True)
    plan = build_step_plan(stages)
    assert [step_id for step_id, _ in plan] == [
        "copy",
        "merge",
        "transcribe",
        "diarize",
        "summarize",
    ]


def test_status_reporter_writes_progress(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    reporter.begin_run(device="NO NAME", sessions_total=2, pipeline="copy → llm")
    reporter.begin_session(
        1,
        label="R2026-06-30-08-44-46.WAV",
        recording_stem="R2026-06-30-08-44-46",
        step_plan=[("copy", "Copy to archive"), ("transcribe", "Transcribe")],
    )
    reporter.set_step_active("copy", detail="1/3 files copied")
    reporter.touch(stage="Copying", progress=0.5, detail="2/3 files copied")
    reporter.mark_step_done("copy")
    reporter.complete_run(processed=1)

    loaded = load_status(path)
    assert loaded.state == STATE_COMPLETE
    assert loaded.device == "NO NAME"
    assert loaded.sessions_total == 2
    assert loaded.session == 1
    assert loaded.steps[0].status == STEP_DONE
    assert loaded.progress == 1.0


def test_menu_bar_title_for_active_session():
    reporter = StatusReporter(enabled=False)
    reporter.begin_run(device="Z29", sessions_total=2, pipeline="full")
    reporter.begin_session(
        1,
        label="session",
        recording_stem="R2026-06-30-08-44-46",
        step_plan=[("diarize", "Diarize speakers")],
    )
    reporter.set_step_active("diarize")
    title = menu_bar_title(reporter._status)
    assert title == "⟳ Diarize speakers 1/2"


def test_status_reporter_context_activation(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    with reporter.activate():
        reporter.begin_run(device="NO NAME", sessions_total=1, pipeline="llm")
        reporter.touch(stage="Summarizing", detail="grok")
    loaded = load_status(path)
    assert loaded.state == STATE_PROCESSING
    assert loaded.stage == "Summarizing"