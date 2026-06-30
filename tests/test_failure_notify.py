"""Tests for session failure notifications."""

from unittest.mock import patch

from ideaforge.notify import format_failure_notification, notify_session_failure


def test_format_failure_notification_truncates_error():
    title, subtitle, message = format_failure_notification(
        "R2026-06-30-08-00-00",
        "x" * 300,
    )
    assert title == "IdeaForge"
    assert subtitle == "Session failed"
    assert len(message) < 300
    assert message.startswith("R2026-06-30-08-00-00")


def test_notify_session_failure_dispatches_mac_notification(capsys):
    with patch("ideaforge.notify.notify_mac", return_value=True) as notify:
        assert notify_session_failure("R2026-06-30-08-00-00", "boom") is True
    notify.assert_called_once()
    assert "Failure notification sent" in capsys.readouterr().out


def test_runner_notifies_on_failure_when_enabled(tmp_path):
    from datetime import datetime

    import numpy as np
    import wave

    from ideaforge.config import IdeaForgeConfig
    from ideaforge.pipeline import PipelineStages
    from ideaforge.runner import process_source

    source = tmp_path / "device" / "RECORD"
    archive = tmp_path / "IdeaForge"
    source.mkdir(parents=True)
    wav = source / datetime(2026, 6, 30, 8, 0, 0).strftime("R%Y-%m-%d-%H-%M-%S.WAV")
    rate = 12000
    samples = np.zeros(rate * 5, dtype=np.int16)
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())

    cfg = IdeaForgeConfig(archive=archive, notify_on_failure=True)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=False)

    with (
        patch(
            "ideaforge.session_worker.transcribe_audio",
            side_effect=RuntimeError("gpu oom"),
        ),
        patch("ideaforge.runner.notify_session_failure") as notify_failure,
    ):
        process_source(
            source,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    notify_failure.assert_called_once()
    assert notify_failure.call_args.args[0] == "R2026-06-30-08-00-00"