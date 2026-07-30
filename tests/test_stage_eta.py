"""Tests for rough stage ETA estimates."""

from ideaforge.stage_eta import (
    RTF_DIARIZE,
    RTF_TRANSCRIBE,
    estimate_remaining_seconds,
    estimate_stage_seconds,
    format_eta_label,
    rtf_for_stage,
)
from ideaforge.status import (
    STATE_PROCESSING,
    PipelineStatus,
    StatusReporter,
    Stage,
    format_eta,
)


def test_rtf_for_known_stages():
    assert rtf_for_stage("Transcribing") == RTF_TRANSCRIBE
    assert rtf_for_stage("Diarize speakers") == RTF_DIARIZE
    assert rtf_for_stage("Idle") is None


def test_estimate_transcribe_40_min_audio():
    # 40 min audio * 0.025 RTF ≈ 60s wall
    total = estimate_stage_seconds(
        stage="Transcribing",
        audio_duration_seconds=40 * 60,
    )
    assert total is not None
    assert 55 <= total <= 65


def test_remaining_uses_progress():
    remaining = estimate_remaining_seconds(
        stage="Transcribing",
        audio_duration_seconds=40 * 60,
        progress=0.5,
    )
    assert remaining is not None
    assert 25 <= remaining <= 35


def test_remaining_uses_elapsed_when_no_progress():
    remaining = estimate_remaining_seconds(
        stage="Diarizing",
        audio_duration_seconds=60 * 60,
        stage_elapsed_seconds=100,
    )
    total = estimate_stage_seconds(stage="Diarizing", audio_duration_seconds=60 * 60)
    assert remaining is not None and total is not None
    assert abs(remaining - (total - 100)) < 0.01


def test_format_eta_label_minutes():
    assert format_eta_label(12 * 60) == "~12m left"
    assert format_eta_label(5) == "~moments left"
    assert format_eta_label(None) is None


def test_status_reporter_sets_eta(tmp_path):
    path = tmp_path / "status.json"
    reporter = StatusReporter(path)
    reporter.begin_run(device="Z28", sessions_total=1, pipeline="transcribe")
    reporter.touch(
        stage=Stage.TRANSCRIBING,
        audio_duration_seconds=40 * 60,
        clear_progress=True,
    )
    loaded = PipelineStatus.from_dict(
        __import__("json").loads(path.read_text(encoding="utf-8"))
    )
    assert loaded.state == STATE_PROCESSING or loaded.stage == Stage.TRANSCRIBING
    assert loaded.eta_seconds is not None
    assert loaded.eta_seconds > 0
    label = format_eta(loaded)
    assert label is not None
    assert "left" in label
