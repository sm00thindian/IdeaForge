"""Tests for pipeline status reporting."""

from ideaforge.pipeline import PipelineStages
from ideaforge.status import (
    STATE_COMPLETE,
    STATE_PROCESSING,
    STATE_SETTLING,
    STEP_ACTIVE,
    STEP_DONE,
    Stage,
    StatusReporter,
    StepId,
    StepLabel,
    build_step_plan,
    load_status,
    menu_bar_title,
)


def test_build_step_plan_includes_pipeline_stages():
    stages = PipelineStages(copy=True, transcribe=True, diarize=True, llm=True)
    plan = build_step_plan(stages)
    assert [step_id for step_id, _ in plan] == [
        StepId.COPY,
        StepId.MERGE,
        StepId.TRANSCRIBE,
        StepId.DIARIZE,
        StepId.SUMMARIZE,
    ]


def test_status_reporter_writes_progress(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    reporter.begin_run(device="NO NAME", sessions_total=2, pipeline="copy → llm")
    reporter.begin_session(
        1,
        label="R2026-06-30-08-44-46.WAV",
        recording_stem="R2026-06-30-08-44-46",
        step_plan=[(StepId.COPY, StepLabel.COPY), (StepId.TRANSCRIBE, StepLabel.TRANSCRIBE)],
    )
    reporter.set_step_active(StepId.COPY, detail="1/3 files copied")
    reporter.touch(stage=Stage.COPYING, progress=0.5, detail="2/3 files copied")
    reporter.mark_step_done(StepId.COPY)
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
        step_plan=[(StepId.DIARIZE, StepLabel.DIARIZE)],
    )
    reporter.set_step_active(StepId.DIARIZE)
    title = menu_bar_title(reporter._status)
    assert title == "⟳ Diarize speakers 1/2"


def test_enter_processing_leaves_settling_state(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    reporter.set_settling(device="NO NAME", recording_count=3)
    reporter.enter_processing(
        device="NO NAME",
        stage=Stage.INGESTING,
        detail="0/3 files copied",
        progress=0.0,
    )
    loaded = load_status(path)
    assert loaded.state == STATE_PROCESSING
    assert loaded.stage == Stage.INGESTING
    assert loaded.state != STATE_SETTLING


def test_update_run_preserves_processing_state(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    reporter.enter_processing(device="NO NAME", stage=Stage.INGESTING)
    reporter.update_run(sessions_total=2, pipeline="transcribe → llm")
    loaded = load_status(path)
    assert loaded.state == STATE_PROCESSING
    assert loaded.sessions_total == 2
    assert loaded.pipeline == "transcribe → llm"


def test_status_reporter_context_activation(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    with reporter.activate():
        reporter.begin_run(device="NO NAME", sessions_total=1, pipeline="llm")
        reporter.touch(stage=Stage.SUMMARIZING, detail="grok")
    loaded = load_status(path)
    assert loaded.state == STATE_PROCESSING
    assert loaded.stage == Stage.SUMMARIZING


def test_stage_constants_are_unique():
    stage_values = [value for key, value in vars(Stage).items() if not key.startswith("_")]
    step_id_values = [value for key, value in vars(StepId).items() if not key.startswith("_")]
    step_label_values = [value for key, value in vars(StepLabel).items() if not key.startswith("_")]
    assert len(stage_values) == len(set(stage_values))
    assert len(step_id_values) == len(set(step_id_values))
    assert len(step_label_values) == len(set(step_label_values))