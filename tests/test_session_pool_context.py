"""Tests for parallel session context propagation."""

from datetime import datetime
from pathlib import Path

from ideaforge.chunks import RecordingChunk, RecordingGroup
from ideaforge.status import StatusReporter, active_reporter


def _group(stem: str) -> RecordingGroup:
    path = Path(f"{stem}.WAV")
    chunk = RecordingChunk(path=path, start=datetime(2026, 6, 30, 10, 0, 0), duration_seconds=60.0)
    return RecordingGroup(chunks=(chunk,))


def test_parallel_workers_inherit_active_reporter():
    reporter = StatusReporter(enabled=False)
    groups = [_group("R2026-06-30-10-00-00"), _group("R2026-06-30-11-00-00")]
    seen: list[str] = []

    def run_one(_index: int, group: RecordingGroup) -> tuple[int, int, object]:
        current = active_reporter()
        seen.append(group.session_stem if current is reporter else "missing")
        return (1, 0, object())

    with reporter.activate():
        from ideaforge.session_pool import run_session_groups

        run_session_groups(
            groups,
            run_one=run_one,
            max_workers=2,
            reporter=reporter,
            on_failure=lambda _g, _e: None,
            show_progress=False,
        )

    assert len(seen) == 2
    assert "missing" not in seen