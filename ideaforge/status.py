"""Pipeline status for desktop progress UI (menu bar, notifications)."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_active_reporter: ContextVar[Optional["StatusReporter"]] = ContextVar(
    "ideaforge_status_reporter",
    default=None,
)

STEP_PENDING = "pending"
STEP_ACTIVE = "active"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"

STATE_IDLE = "idle"
STATE_WATCHING = "watching"
STATE_SETTLING = "settling"
STATE_PROCESSING = "processing"
STATE_COMPLETE = "complete"
STATE_ERROR = "error"


class Stage:
    """Pipeline and daemon stage labels written to ``status.stage``."""

    SYNCING_CLOCK = "Syncing clock"
    INGESTING = "Ingesting"
    COPYING = "Copying"
    TRANSCRIBING = "Transcribing"
    DIARIZING = "Diarizing"
    SUMMARIZING = "Summarizing"
    IDLE = "Idle"
    WATCHING = "Watching"
    SETTLING = "Settling"
    STARTING = "Starting"
    PREPARING = "Preparing"
    ERROR = "Error"
    COMPLETE = "Complete"
    PROCESSING = "Processing"


class StepId:
    """Pipeline step identifiers for ``StatusReporter`` step tracking."""

    COPY = "copy"
    MERGE = "merge"
    TRANSCRIBE = "transcribe"
    DIARIZE = "diarize"
    SUMMARIZE = "summarize"


class StepLabel:
    """Human-readable labels shown in the menu bar when a step is active."""

    COPY = "Copy to archive"
    MERGE = "Merge chunks"
    TRANSCRIBE = "Transcribe"
    DIARIZE = "Diarize speakers"
    SUMMARIZE = "Meeting notes"


def default_status_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "IdeaForge" / "status.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@dataclass
class StatusStep:
    id: str
    label: str
    status: str = STEP_PENDING

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class PipelineStatus:
    state: str = STATE_IDLE
    device: Optional[str] = None
    session: int = 0
    sessions_total: int = 0
    recording: Optional[str] = None
    stage: Optional[str] = None
    progress: Optional[float] = None
    detail: Optional[str] = None
    pipeline: Optional[str] = None
    active_sessions: int = 0
    steps: List[StatusStep] = field(default_factory=list)
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineStatus":
        steps = [
            StatusStep(
                id=str(item.get("id", "")),
                label=str(item.get("label", "")),
                status=str(item.get("status", STEP_PENDING)),
            )
            for item in data.get("steps", [])
        ]
        return cls(
            state=str(data.get("state", STATE_IDLE)),
            device=data.get("device"),
            session=int(data.get("session", 0) or 0),
            sessions_total=int(data.get("sessions_total", 0) or 0),
            recording=data.get("recording"),
            stage=data.get("stage"),
            progress=data.get("progress"),
            detail=data.get("detail"),
            pipeline=data.get("pipeline"),
            active_sessions=int(data.get("active_sessions", 0) or 0),
            steps=steps,
            started_at=data.get("started_at"),
            updated_at=data.get("updated_at"),
            elapsed_seconds=data.get("elapsed_seconds"),
            error=data.get("error"),
        )


def load_status(path: Optional[Path] = None) -> PipelineStatus:
    status_path = path or default_status_path()
    if not status_path.is_file():
        return PipelineStatus()
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        return PipelineStatus.from_dict(data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return PipelineStatus()


def save_status(status: PipelineStatus, path: Optional[Path] = None) -> None:
    status_path = path or default_status_path()
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status.updated_at = _utc_now()
    if status.started_at:
        try:
            started = datetime.fromisoformat(status.started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = datetime.now(timezone.utc) - started
            status.elapsed_seconds = round(elapsed.total_seconds(), 1)
        except ValueError:
            status.elapsed_seconds = None
    status_path.write_text(
        json.dumps(status.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def menu_bar_title(status: PipelineStatus) -> str:
    if status.state in (STATE_IDLE, STATE_WATCHING):
        return "IdeaForge"
    if status.state == STATE_SETTLING:
        return "⟳ Settling…"
    if status.state == STATE_COMPLETE:
        return "✓ IdeaForge"
    if status.state == STATE_ERROR:
        return "⚠ IdeaForge"

    stage = status.stage or Stage.PROCESSING
    if status.active_sessions > 1:
        return f"⟳ {stage} · {status.active_sessions} active"
    if status.sessions_total > 1 and status.session:
        return f"⟳ {stage} {status.session}/{status.sessions_total}"
    return f"⟳ {stage}"


def format_elapsed(status: PipelineStatus) -> str:
    if status.elapsed_seconds is None:
        return "—"
    return _format_duration(status.elapsed_seconds)


def active_reporter() -> Optional["StatusReporter"]:
    return _active_reporter.get()


def status_touch(
    *,
    stage: Optional[str] = None,
    progress: Optional[float] = None,
    detail: Optional[str] = None,
    clear_progress: bool = False,
) -> None:
    reporter = active_reporter()
    if reporter is None:
        return
    reporter.touch(stage=stage, progress=progress, detail=detail, clear_progress=clear_progress)


class StatusReporter:
    """Writes structured pipeline progress for the menu bar and other UIs."""

    def __init__(self, path: Optional[Path] = None, *, enabled: bool = True) -> None:
        self.path = path or default_status_path()
        self.enabled = enabled
        self._status = PipelineStatus()
        self._run_started_at: Optional[float] = None
        self._step_ids: List[str] = []
        self._lock = threading.Lock()
        self._active_sessions = 0

    def _write(self) -> None:
        if self.enabled:
            with self._lock:
                self._status.active_sessions = self._active_sessions
                save_status(self._status, self.path)

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
        self._status.state = STATE_WATCHING
        self._status.device = device
        self._status.stage = Stage.WATCHING
        self._status.detail = "Monitoring /Volumes for recorder"
        self._status.progress = None
        self._status.error = None
        self._write()

    def set_settling(self, *, device: str, recording_count: int) -> None:
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
            started_at=_utc_now(),
            steps=[],
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
        self._status.state = STATE_PROCESSING
        self._status.session = session_index
        self._status.recording = label
        self._status.stage = Stage.PREPARING
        self._status.progress = None
        self._status.detail = recording_stem
        self._status.error = None
        self._step_ids = [step_id for step_id, _ in step_plan]
        self._status.steps = [
            StatusStep(id=step_id, label=step_label) for step_id, step_label in step_plan
        ]
        self._write()

    def set_step_active(self, step_id: str, *, detail: Optional[str] = None) -> None:
        for step in self._status.steps:
            if step.id == step_id:
                step.status = STEP_ACTIVE
                self._status.stage = step.label
            elif step.status == STEP_ACTIVE:
                step.status = STEP_DONE
        if detail is not None:
            self._status.detail = detail
        self._write()

    def mark_step_done(self, step_id: str) -> None:
        for step in self._status.steps:
            if step.id == step_id:
                step.status = STEP_DONE
        self._write()

    def skip_step(self, step_id: str) -> None:
        for step in self._status.steps:
            if step.id == step_id:
                step.status = STEP_SKIPPED
        self._write()

    def touch(
        self,
        *,
        stage: Optional[str] = None,
        progress: Optional[float] = None,
        detail: Optional[str] = None,
        clear_progress: bool = False,
    ) -> None:
        if stage is not None:
            self._status.stage = stage
        if clear_progress:
            self._status.progress = None
        elif progress is not None:
            self._status.progress = max(0.0, min(1.0, progress))
        if detail is not None:
            self._status.detail = detail
        self._write()

    def set_error(self, message: str) -> None:
        self._status.state = STATE_ERROR
        self._status.stage = Stage.ERROR
        self._status.detail = message
        self._status.error = message
        self._status.progress = None
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
        self._status.progress = 1.0
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