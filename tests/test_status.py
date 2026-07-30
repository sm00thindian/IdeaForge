"""Tests for pipeline status reporting."""

import os
from unittest.mock import patch

from ideaforge.pipeline import PipelineStages
from ideaforge.status import (
    STATE_COMPLETE,
    STATE_PROCESSING,
    STATE_SETTLING,
    STATE_WATCHING,
    STEP_ACTIVE,
    STEP_DONE,
    Stage,
    StatusReporter,
    StepId,
    StepLabel,
    build_step_plan,
    is_status_owned_by_other,
    load_status,
    menu_bar_title,
    resolve_display_status,
    save_status,
    PipelineStatus,
    StatusStep,
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


def test_daemon_does_not_overwrite_foreign_processing_status(tmp_path):
    path = tmp_path / "status.json"
    cli_pid = os.getpid() + 50000
    save_status(
        PipelineStatus(
            state=STATE_PROCESSING,
            device="2026-07-02",
            sessions_total=3,
            stage=Stage.DIARIZING,
            detail="R2014-10-27-13-09-15_merged.wav",
            owner_pid=cli_pid,
        ),
        path,
    )
    daemon = StatusReporter(path)
    with patch("ideaforge.status_cli_probe._pid_alive", return_value=True):
        daemon.set_watching(device="IdeaForge")
    loaded = load_status(path)
    assert loaded.state == STATE_PROCESSING
    assert loaded.stage == Stage.DIARIZING
    assert loaded.owner_pid == cli_pid


def test_daemon_can_watch_after_foreign_owner_completes(tmp_path):
    path = tmp_path / "status.json"
    save_status(
        PipelineStatus(
            state=STATE_COMPLETE,
            device="2026-07-02",
            stage=Stage.COMPLETE,
            detail="3 session(s) processed",
        ),
        path,
    )
    daemon = StatusReporter(path)
    with patch("ideaforge.status_cli_probe.find_cli_pipeline_pids", return_value=[]):
        daemon.set_watching()
    loaded = load_status(path)
    assert loaded.state == STATE_WATCHING


def test_daemon_skips_watching_when_cli_pipeline_running(tmp_path):
    path = tmp_path / "status.json"
    save_status(PipelineStatus(state=STATE_WATCHING), path)
    daemon = StatusReporter(path)
    with patch("ideaforge.status_cli_probe.find_cli_pipeline_pids", return_value=[4242]):
        daemon.set_watching(device="IdeaForge")
    loaded = load_status(path)
    assert loaded.state == STATE_WATCHING


def test_resolve_display_status_detects_cli_pipeline():
    status = PipelineStatus(state=STATE_WATCHING)
    enriched = PipelineStatus(
        state=STATE_PROCESSING,
        device="2026-07-02",
        session=2,
        sessions_total=3,
        stage=Stage.DIARIZING,
        detail="R2014-10-27-14-31-06_merged",
        pipeline="transcribe → diarize → llm",
        elapsed_seconds=120.0,
        steps=[
            StatusStep(id=StepId.TRANSCRIBE, label=StepLabel.TRANSCRIBE, status=STEP_DONE),
            StatusStep(id=StepId.DIARIZE, label=StepLabel.DIARIZE, status=STEP_ACTIVE),
        ],
    )
    with patch("ideaforge.status_cli_probe.find_cli_pipeline_pids", return_value=[4242]):
        with patch(
            "ideaforge.status_cli_probe._status_from_cli_pipeline",
            return_value=enriched,
        ):
            shown = resolve_display_status(status)
    assert shown.state == STATE_PROCESSING
    assert shown.stage == Stage.DIARIZING
    assert shown.sessions_total == 3
    assert menu_bar_title(shown) == "⟳ Diarizing 2/3"


def test_parse_ps_elapsed_accepts_macos_formats():
    from ideaforge.status import _parse_ps_elapsed

    assert _parse_ps_elapsed("35:42") == 35 * 60 + 42
    assert _parse_ps_elapsed("01:23:45") == 1 * 3600 + 23 * 60 + 45
    assert _parse_ps_elapsed("02-03:45:30") == 2 * 86400 + 3 * 3600 + 45 * 60 + 30


def test_parse_cli_log_progress_reads_stage_and_sessions():
    log_text = """
   Found 38 audio file(s) in 3 session(s)
   Pipeline: transcribe → diarize → llm
    ✓ Markdown saved: R2014-10-27-13-09-15_summary.md
    🎙️  Transcribing R2014-10-27-14-31-06_merged.wav ...
    🗣️  Running pyannote speaker diarization (min=1, max=6) ...
"""
    from ideaforge.status import _parse_cli_log_progress

    parsed = _parse_cli_log_progress(log_text)
    assert parsed["sessions_total"] == 3
    assert parsed["session"] == 2
    assert parsed["stage"] == Stage.DIARIZING
    assert parsed["recording"] == "R2014-10-27-14-31-06_merged"


def test_is_status_owned_by_other_ignores_same_pid(tmp_path):
    path = tmp_path / "status.json"
    save_status(
        PipelineStatus(
            state=STATE_PROCESSING,
            owner_pid=os.getpid(),
        ),
        path,
    )
    with patch("ideaforge.status.find_cli_pipeline_pids", return_value=[]):
        assert is_status_owned_by_other(path) is False


def test_stage_constants_are_unique():
    stage_values = [value for key, value in vars(Stage).items() if not key.startswith("_")]
    step_id_values = [value for key, value in vars(StepId).items() if not key.startswith("_")]
    step_label_values = [value for key, value in vars(StepLabel).items() if not key.startswith("_")]
    assert len(stage_values) == len(set(stage_values))
    assert len(step_id_values) == len(set(step_id_values))
    assert len(step_label_values) == len(set(step_label_values))


def test_reporter_relabels_summarize_step_and_sets_intent(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    reporter.begin_session(
        1,
        label="memo",
        recording_stem="R2026-06-27-07-43-11",
        step_plan=[(StepId.SUMMARIZE, StepLabel.SUMMARIZE)],
    )
    reporter.relabel_step(StepId.SUMMARIZE, StepLabel.SONG_IDEA)
    reporter.set_output_intent("song_idea")
    reporter.set_step_active(StepId.SUMMARIZE, detail="R2026-06-27-07-43-11")

    saved = load_status(path)
    assert saved.output_intent == "song_idea"
    assert saved.stage == StepLabel.SONG_IDEA
    assert saved.steps[0].label == StepLabel.SONG_IDEA