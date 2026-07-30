"""StatusReporter and active-reporter context for pipeline UI."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator, List, Optional

from ideaforge.status_cli_probe import is_status_owned_by_other
from ideaforge.status_model import (
    STATE_COMPLETE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PROCESSING,
    STATE_SETTLING,
    STATE_WATCHING,
    STEP_ACTIVE,
    STEP_DONE,
    STEP_SKIPPED,
    Stage,
    StatusStep,
    StepId,
    StepLabel,
    PipelineStatus,
    default_status_path,
    save_status,
    utc_now,
)

_active_reporter: ContextVar[Optional["StatusReporter"]] = ContextVar(
    "ideaforge_status_reporter",
    default=None,
)

def active_reporter() -> Optional["StatusReporter"]:
    return _active_reporter.get()


def run_with_active_reporter(reporter: Optional["StatusReporter"], fn, /, *args, **kwargs):
    """Run ``fn`` with ``reporter`` bound for ``active_reporter()`` (thread-safe)."""
    token = _active_reporter.set(reporter)
    try:
        return fn(*args, **kwargs)
    finally:
        _active_reporter.reset(token)


def status_touch(
    *,
    stage: Optional[str] = None,
    progress: Optional[float] = None,
    detail: Optional[str] = None,
    clear_progress: bool = False,
    audio_duration_seconds: Optional[float] = None,
    clear_eta: bool = False,
) -> None:
    reporter = active_reporter()
    if reporter is None:
        return
    reporter.touch(
        stage=stage,
        progress=progress,
        detail=detail,
        clear_progress=clear_progress,
        audio_duration_seconds=audio_duration_seconds,
        clear_eta=clear_eta,
    )


class StatusReporter:
    """Writes structured pipeline progress for the menu bar and other UIs."""

    def __init__(self, path: Optional[Path] = None, *, enabled: bool = True) -> None:
        self.path = path or default_status_path()
        self.enabled = enabled
        self._owner_pid = os.getpid()
        self._status = PipelineStatus()
        self._run_started_at: Optional[float] = None
        self._step_ids: List[str] = []
        self._lock = threading.RLock()
        self._active_sessions = 0
        self._stage_started_at: Optional[float] = None

    def _claim_owner(self) -> None:
        self._status.owner_pid = self._owner_pid

    def _skip_if_foreign_owner(self) -> bool:
        return is_status_owned_by_other(self.path, my_pid=self._owner_pid)

    def _write(self) -> None:
        if self.enabled:
            with self._lock:
                if self._status.state in (STATE_PROCESSING, STATE_SETTLING):
                    self._claim_owner()
                self._status.active_sessions = self._active_sessions
                save_status(self._status, self.path)

    def enter_processing(
        self,
        *,
        device: str,
        stage: str,
        detail: Optional[str] = None,
        progress: Optional[float] = None,
    ) -> None:
        """Move from settling/watching into an active pipeline stage (ingest, transcribe, …)."""
        with self._lock:
            self._status.state = STATE_PROCESSING
            self._status.device = device
            self._status.stage = stage
            if detail is not None:
                self._status.detail = detail
            if progress is not None:
                self._status.progress = max(0.0, min(1.0, progress))
            if self._status.started_at is None:
                self._status.started_at = utc_now()
            self._status.error = None
            self._claim_owner()
        self._write()

    def update_run(self, *, sessions_total: int, pipeline: str) -> None:
        """Refresh session count when continuing an in-flight daemon run."""
        with self._lock:
            self._status.sessions_total = sessions_total
            self._status.pipeline = pipeline
            self._status.state = STATE_PROCESSING
        self._write()

    @contextmanager
    def track_session(self) -> Iterator[None]:
        with self._lock:
            self._active_sessions += 1
        self._write()
        try:
            yield
        finally:
            with self._lock:
                self._active_sessions = max(0, self._active_sessions - 1)
            self._write()

    def set_idle(self, *, device: Optional[str] = None, detail: Optional[str] = None) -> None:
        if self._skip_if_foreign_owner():
            return
        self._status = PipelineStatus(
            state=STATE_IDLE,
            device=device,
            stage=Stage.IDLE,
            detail=detail or "Waiting for recordings",
            steps=[],
        )
        self._run_started_at = None
        self._write()

    def set_watching(self, *, device: Optional[str] = None) -> None:
        if self._skip_if_foreign_owner():
            return
        self._status.state = STATE_WATCHING
        self._status.device = device
        self._status.stage = Stage.WATCHING
        self._status.detail = "Monitoring /Volumes for recorder"
        self._status.progress = None
        self._status.error = None
        self._status.owner_pid = None
        self._write()

    def set_settling(self, *, device: str, recording_count: int) -> None:
        if self._skip_if_foreign_owner():
            return
        self._status.state = STATE_SETTLING
        self._status.device = device
        self._status.stage = Stage.SETTLING
        self._status.detail = f"{recording_count} recording(s) detected — waiting for mount"
        self._status.progress = None
        self._write()

    def begin_run(
        self,
        *,
        device: str,
        sessions_total: int,
        pipeline: str,
    ) -> None:
        self._run_started_at = time.monotonic()
        self._status = PipelineStatus(
            state=STATE_PROCESSING,
            device=device,
            sessions_total=sessions_total,
            pipeline=pipeline,
            stage=Stage.STARTING,
            detail=f"{sessions_total} session(s) queued",
            started_at=utc_now(),
            steps=[],
            owner_pid=self._owner_pid,
        )
        self._step_ids = []
        self._write()

    def begin_session(
        self,
        session_index: int,
        *,
        label: str,
        recording_stem: str,
        step_plan: List[tuple[str, str]],
    ) -> None:
        with self._lock:
            self._status.state = STATE_PROCESSING
            self._status.session = session_index
            self._status.recording = label
            self._status.stage = Stage.PREPARING
            self._status.progress = None
            self._status.detail = recording_stem
            self._status.error = None
            self._status.eta_seconds = None
            self._status.audio_duration_seconds = None
            self._stage_started_at = None
            self._step_ids = [step_id for step_id, _ in step_plan]
            self._status.steps = [
                StatusStep(id=step_id, label=step_label) for step_id, step_label in step_plan
            ]
        self._write()

    def set_step_active(self, step_id: str, *, detail: Optional[str] = None) -> None:
        with self._lock:
            for step in self._status.steps:
                if step.id == step_id:
                    step.status = STEP_ACTIVE
                    self._status.stage = step.label
                    self._stage_started_at = time.monotonic()
                elif step.status == STEP_ACTIVE:
                    step.status = STEP_DONE
            if detail is not None:
                self._status.detail = detail
            self._refresh_eta_locked()
        self._write()

    def relabel_step(self, step_id: str, label: str) -> None:
        with self._lock:
            for step in self._status.steps:
                if step.id == step_id:
                    step.label = label
                    if step.status == STEP_ACTIVE:
                        self._status.stage = label
        self._write()

    def set_output_intent(self, output_intent: Optional[str]) -> None:
        self._status.output_intent = output_intent
        self._write()

    def mark_step_done(self, step_id: str) -> None:
        with self._lock:
            for step in self._status.steps:
                if step.id == step_id:
                    step.status = STEP_DONE
            self._status.eta_seconds = None
        self._write()

    def skip_step(self, step_id: str) -> None:
        with self._lock:
            for step in self._status.steps:
                if step.id == step_id:
                    step.status = STEP_SKIPPED
            self._status.eta_seconds = None
        self._write()

    def _refresh_eta_locked(self) -> None:
        from ideaforge.stage_eta import estimate_remaining_seconds

        stage_elapsed = None
        if self._stage_started_at is not None:
            stage_elapsed = time.monotonic() - self._stage_started_at
        self._status.eta_seconds = estimate_remaining_seconds(
            stage=self._status.stage,
            audio_duration_seconds=self._status.audio_duration_seconds,
            progress=self._status.progress,
            stage_elapsed_seconds=stage_elapsed,
        )

    def touch(
        self,
        *,
        stage: Optional[str] = None,
        progress: Optional[float] = None,
        detail: Optional[str] = None,
        clear_progress: bool = False,
        audio_duration_seconds: Optional[float] = None,
        clear_eta: bool = False,
    ) -> None:
        with self._lock:
            if stage is not None:
                if stage != self._status.stage:
                    self._stage_started_at = time.monotonic()
                self._status.stage = stage
            if clear_progress:
                self._status.progress = None
            elif progress is not None:
                self._status.progress = max(0.0, min(1.0, progress))
            if detail is not None:
                self._status.detail = detail
            if audio_duration_seconds is not None:
                self._status.audio_duration_seconds = max(
                    0.0, float(audio_duration_seconds)
                )
            if clear_eta:
                self._status.eta_seconds = None
                self._status.audio_duration_seconds = None
            else:
                self._refresh_eta_locked()
        self._write()

    def set_error(self, message: str) -> None:
        self._status.state = STATE_ERROR
        self._status.stage = Stage.ERROR
        self._status.detail = message
        self._status.error = message
        self._status.progress = None
        self._status.eta_seconds = None
        self._write()

    def complete_run(self, *, processed: int, skipped: int = 0) -> None:
        if processed == 0 and skipped > 0:
            detail = f"{skipped} session(s) already up to date"
        elif processed == 1:
            detail = "1 session processed"
        else:
            detail = f"{processed} session(s) processed"
        self._status.state = STATE_COMPLETE
        self._status.stage = Stage.COMPLETE
        self._status.detail = detail
        self._status.eta_seconds = None
        self._status.progress = 1.0
        self._status.owner_pid = None
        for step in self._status.steps:
            if step.status == STEP_ACTIVE:
                step.status = STEP_DONE
        self._write()

    @contextmanager
    def activate(self) -> Iterator["StatusReporter"]:
        token = _active_reporter.set(self)
        try:
            yield self
        finally:
            _active_reporter.reset(token)


def build_step_plan(stages) -> List[tuple[str, str]]:
    """Build ordered pipeline steps from resolved stage flags."""
    plan: List[tuple[str, str]] = []
    if stages.copy:
        plan.append((StepId.COPY, StepLabel.COPY))
    if stages.transcribe:
        plan.append((StepId.MERGE, StepLabel.MERGE))
        plan.append((StepId.TRANSCRIBE, StepLabel.TRANSCRIBE))
        if stages.diarize:
            plan.append((StepId.DIARIZE, StepLabel.DIARIZE))
    elif stages.diarize:
        plan.append((StepId.DIARIZE, StepLabel.DIARIZE))
    if stages.llm:
        plan.append((StepId.SUMMARIZE, StepLabel.SUMMARIZE))
    return plan
