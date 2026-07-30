"""Status model, constants, and load/save helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    SONG_IDEA = "Song idea"


def default_status_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "IdeaForge" / "status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Back-compat alias used inside package
_utc_now = utc_now


def format_duration(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


_format_duration = format_duration


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
    owner_pid: Optional[int] = None
    output_intent: Optional[str] = None
    eta_seconds: Optional[float] = None
    audio_duration_seconds: Optional[float] = None

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
        eta = data.get("eta_seconds")
        audio_dur = data.get("audio_duration_seconds")
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
            owner_pid=data.get("owner_pid"),
            output_intent=data.get("output_intent"),
            eta_seconds=float(eta) if eta is not None else None,
            audio_duration_seconds=float(audio_dur) if audio_dur is not None else None,
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
    status.updated_at = utc_now()
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
    return format_duration(status.elapsed_seconds)


def format_eta(status: PipelineStatus) -> Optional[str]:
    """Rough ETA label for menubar / status report, or None."""
    from ideaforge.stage_eta import format_eta_label

    return format_eta_label(status.eta_seconds)
