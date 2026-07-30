"""Pipeline status for desktop progress UI (menu bar, notifications)."""

from __future__ import annotations

import json
import os
import re
import subprocess
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
    SONG_IDEA = "Song idea"


def default_status_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "IdeaForge" / "status.json"


def default_last_notes_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "IdeaForge"
        / "last_notes.json"
    )


@dataclass
class LastNote:
    """Markdown notes from the most recent pipeline run that produced notes."""

    path: str
    title: str
    output_intent: Optional[str] = None
    stem: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "output_intent": self.output_intent,
            "stem": self.stem,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LastNote":
        path = str(data.get("path") or "").strip()
        title = str(data.get("title") or "").strip() or Path(path).stem
        return cls(
            path=path,
            title=title,
            output_intent=data.get("output_intent"),
            stem=data.get("stem"),
        )

    @property
    def menu_label(self) -> str:
        label = self.title.strip() or Path(self.path).stem
        if self.output_intent == "song_idea":
            return f"🎵 {label}"
        return label


def load_last_notes(path: Optional[Path] = None) -> List[LastNote]:
    """Load last-run markdown note links (paths that no longer exist are dropped)."""
    notes_path = path or default_last_notes_path()
    if not notes_path.is_file():
        return []
    try:
        data = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    raw_notes = data.get("notes") if isinstance(data, dict) else data
    if not isinstance(raw_notes, list):
        return []
    notes: List[LastNote] = []
    for item in raw_notes:
        if not isinstance(item, dict):
            continue
        note = LastNote.from_dict(item)
        if not note.path:
            continue
        if Path(note.path).is_file():
            notes.append(note)
    return notes


def save_last_notes(
    notes: List[LastNote],
    path: Optional[Path] = None,
) -> None:
    """Replace the last-run notes list (clears previous links)."""
    notes_path = path or default_last_notes_path()
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _utc_now(),
        "notes": [note.to_dict() for note in notes],
    }
    notes_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def clear_last_notes(path: Optional[Path] = None) -> None:
    """Remove all last-run note links."""
    save_last_notes([], path=path)


def last_notes_from_recordings(recordings: List[Any]) -> List[LastNote]:
    """Build last-note entries from ``RecordingResult``-like objects with summary_md."""
    notes: List[LastNote] = []
    seen: set[str] = set()
    for rec in recordings:
        if getattr(rec, "skipped", False) or getattr(rec, "failed", False):
            continue
        if getattr(rec, "empty", False):
            continue
        summary_md = getattr(rec, "summary_md", None)
        if not summary_md:
            continue
        path_str = str(summary_md).strip()
        if not path_str or path_str in seen:
            continue
        md_path = Path(path_str)
        if not md_path.is_file():
            continue
        seen.add(path_str)
        title = (getattr(rec, "title", None) or "").strip()
        stem = getattr(rec, "stem", None)
        if not title:
            title = stem or md_path.stem
        notes.append(
            LastNote(
                path=str(md_path.resolve()),
                title=str(title),
                output_intent=getattr(rec, "output_intent", None),
                stem=stem,
            )
        )
    return notes


def record_last_notes_from_recordings(
    recordings: List[Any],
    path: Optional[Path] = None,
) -> List[LastNote]:
    """If any markdown notes were produced, replace the last-notes list with them.

    Skips writing the default Application Support store during pytest so unit
    tests do not overwrite the operator's real last-notes menu.
    """
    notes = last_notes_from_recordings(recordings)
    if not notes:
        return notes
    if path is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return notes
    save_last_notes(notes, path=path)
    return notes


def seed_last_notes_from_archive(
    archive: Path,
    *,
    store_path: Optional[Path] = None,
    limit: int = 5,
) -> List[LastNote]:
    """When last_notes is empty, seed from newest friendly markdown under archive.

    Scans date folders for ``YYYYMMDD - *.md`` (and legacy ``*_summary.md``).
    Writes the store only when it was previously empty.
    """
    store = store_path or default_last_notes_path()
    existing = load_last_notes(store)
    if existing:
        return existing

    archive = archive.expanduser()
    if not archive.is_dir():
        return []

    candidates: List[tuple[float, Path]] = []
    # Friendly notes at date-folder roots; also one level of device roots.
    search_roots = [archive]
    try:
        for child in archive.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                search_roots.append(child)
    except OSError:
        pass

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    friendly_re = re.compile(r"^\d{8} - .+\.md$")
    for root in search_roots:
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir() and date_re.match(entry.name):
                try:
                    for md in entry.iterdir():
                        if not md.is_file() or md.suffix.lower() != ".md":
                            continue
                        if friendly_re.match(md.name) or md.name.endswith("_summary.md"):
                            try:
                                mtime = md.stat().st_mtime
                            except OSError:
                                continue
                            candidates.append((mtime, md))
                except OSError:
                    continue

    if not candidates:
        return []

    candidates.sort(key=lambda item: item[0], reverse=True)
    notes: List[LastNote] = []
    for _, md_path in candidates[: max(1, limit)]:
        title = md_path.stem
        # Strip "YYYYMMDD - " prefix for display
        if len(title) > 11 and title[8:11] == " - ":
            title = title[11:]
        notes.append(
            LastNote(
                path=str(md_path.resolve()),
                title=title,
                output_intent=None,
            )
        )
    if notes:
        save_last_notes(notes, path=store)
    return notes


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
    owner_pid: Optional[int] = None
    output_intent: Optional[str] = None

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
            owner_pid=data.get("owner_pid"),
            output_intent=data.get("output_intent"),
        )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


_SERVICE_COMMAND_MARKERS = (
    "--daemon",
    "menubar_app",
    "run-daemon",
    "run-menubar",
    "--status",
    "--validate-config",
    "--detect",
)

_PIPELINE_COMMAND_MARKERS = (
    "--reprocess",
    "--auto-source",
    "--source",
    "--ingest-only",
    "--transcribe-only",
    "--diarize-only",
    "--llm-only",
    "--retry-failed",
)


def _is_ideaforge_runner(command: str) -> bool:
    return bool(
        re.search(r"venv/bin/ideaforge\b", command)
        or re.search(r"Python.*\bideaforge\b", command)
        or re.search(r"-m\s+ideaforge(?:\.|\b)", command)
    )


def _is_cli_pipeline_command(command: str) -> bool:
    if not _is_ideaforge_runner(command):
        return False
    if any(marker in command for marker in _SERVICE_COMMAND_MARKERS):
        return False
    if re.search(r"\bideaforge\s+(device|fleet|speakers|sync)\b", command):
        return False
    return any(marker in command for marker in _PIPELINE_COMMAND_MARKERS)


def find_cli_pipeline_pids(*, exclude_pid: Optional[int] = None) -> List[int]:
    """Return PIDs for interactive pipeline CLI runs (reprocess, --source, etc.)."""
    try:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []

    pids: List[int] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if exclude_pid is not None and pid == exclude_pid:
            continue
        command = parts[1] if len(parts) > 1 else ""
        if _is_cli_pipeline_command(command) and _pid_alive(pid):
            pids.append(pid)
    return sorted(set(pids))


def _parse_ps_elapsed(raw: str) -> Optional[float]:
    """Parse macOS/BSD ``ps -o etime=`` values into seconds."""
    text = raw.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_part, text = text.split("-", 1)
        try:
            days = int(day_part)
        except ValueError:
            return None
    parts = text.split(":")
    try:
        numbers = [int(float(part)) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 3:
        hours, minutes, seconds = numbers
    elif len(numbers) == 2:
        hours = 0
        minutes, seconds = numbers
    else:
        return None
    return float(((days * 24 + hours) * 60 + minutes) * 60 + seconds)


def _process_elapsed_seconds(pid: int) -> Optional[float]:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return _parse_ps_elapsed(completed.stdout)


def _cli_command_for_pid(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip()


def _reprocess_log_for_command(command: str) -> Optional[Path]:
    match = re.search(r"--source\s+(\S+)", command)
    log_dir = Path.home() / "Library/Logs/ideaforge"
    candidates: List[Path] = []
    if match:
        source = Path(match.group(1)).expanduser()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", source.name):
            date_name = source.name
            candidates.append(log_dir / f"reprocess-{date_name}.log")
            candidates.extend(
                sorted(
                    log_dir.glob(f"reprocess-{date_name}.log.*"),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
            )
    if not candidates:
        candidates = sorted(
            log_dir.glob("reprocess-*.log*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _read_log_tail(path: Path, *, max_bytes: int = 96_000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _steps_for_pipeline_label(
    pipeline: str,
    *,
    active_step_id: Optional[str],
) -> List[StatusStep]:
    plan: List[tuple[str, str]] = []
    lowered = pipeline.lower()
    if "copy" in lowered:
        plan.append((StepId.COPY, StepLabel.COPY))
    if "transcribe" in lowered:
        plan.append((StepId.MERGE, StepLabel.MERGE))
        plan.append((StepId.TRANSCRIBE, StepLabel.TRANSCRIBE))
    if "diarize" in lowered:
        plan.append((StepId.DIARIZE, StepLabel.DIARIZE))
    if "llm" in lowered:
        plan.append((StepId.SUMMARIZE, StepLabel.SUMMARIZE))
    if not plan and "diarize" not in lowered:
        plan.append((StepId.TRANSCRIBE, StepLabel.TRANSCRIBE))

    seen_active = False
    steps: List[StatusStep] = []
    for step_id, label in plan:
        if step_id == active_step_id:
            status = STEP_ACTIVE
            seen_active = True
        elif seen_active:
            status = STEP_PENDING
        else:
            status = STEP_DONE
        steps.append(StatusStep(id=step_id, label=label, status=status))
    if active_step_id and not any(step.id == active_step_id for step in steps):
        steps.append(
            StatusStep(id=active_step_id, label=Stage.PROCESSING, status=STEP_ACTIVE)
        )
    return steps


def _parse_cli_log_progress(log_text: str) -> dict[str, Any]:
    sessions_total = 0
    match = re.search(r"in (\d+) session\(s\)", log_text)
    if match:
        sessions_total = int(match.group(1))

    pipeline = "transcribe → diarize → llm"
    match = re.search(r"Pipeline:\s+(.+)", log_text)
    if match:
        pipeline = match.group(1).strip()

    completed = len(re.findall(r"✓ Markdown saved:", log_text))
    session_index = min(completed + 1, sessions_total) if sessions_total else max(completed, 1)

    stage = Stage.PROCESSING
    active_step_id: Optional[str] = None
    recording: Optional[str] = None
    progress: Optional[float] = None

    stage_rules = [
        (r"🎵 Song idea", Stage.SUMMARIZING, StepId.SUMMARIZE),
        (r"🤖 xAI Grok.*song idea", Stage.SUMMARIZING, StepId.SUMMARIZE),
        (r"🤖 xAI Grok", Stage.SUMMARIZING, StepId.SUMMARIZE),
        (r"🗣️\s+Running pyannote|🗣️\s+Diarizing", Stage.DIARIZING, StepId.DIARIZE),
        (r"🎙️\s+Transcribing", Stage.TRANSCRIBING, StepId.TRANSCRIBE),
        (r"🔗 Merged", Stage.PREPARING, StepId.MERGE),
    ]
    best_pos = -1
    for pattern, stage_label, step_id in stage_rules:
        for match in re.finditer(pattern, log_text):
            if match.start() > best_pos:
                best_pos = match.start()
                stage = stage_label
                active_step_id = step_id

    for pattern in (
        r"🎙️\s+Transcribing\s+(\S+)",
        r"🔗 Merged[^\n]*→\s+(\S+)",
        r"R20\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}[^\s]*_merged\.wav",
    ):
        file_match = re.findall(pattern, log_text)
        if file_match:
            recording = Path(file_match[-1]).stem
            break

    if stage == Stage.TRANSCRIBING:
        tqdm_match = re.findall(r"(\d+)%\|[^|]*\|\s*(\d+)/(\d+)", log_text)
        if tqdm_match:
            pct, _, total = tqdm_match[-1]
            if int(total) > 0:
                progress = int(pct) / 100.0

    device = None
    match = re.search(r"Archive:\s+(\S+)", log_text)
    if match:
        device = Path(match.group(1)).name

    return {
        "sessions_total": sessions_total,
        "session": session_index,
        "pipeline": pipeline,
        "stage": stage,
        "active_step_id": active_step_id,
        "recording": recording,
        "progress": progress,
        "device": device,
        "completed": completed,
    }


def _status_from_cli_pipeline(pid: int) -> Optional[PipelineStatus]:
    command = _cli_command_for_pid(pid)
    if not command:
        return None
    log_path = _reprocess_log_for_command(command)
    log_text = _read_log_tail(log_path) if log_path else ""
    hint_detail, hint_device = _cli_pipeline_hint(pid)

    if log_text:
        parsed = _parse_cli_log_progress(log_text)
        steps = _steps_for_pipeline_label(
            parsed["pipeline"],
            active_step_id=parsed["active_step_id"],
        )
        recording = parsed["recording"]
        return PipelineStatus(
            state=STATE_PROCESSING,
            device=hint_device or parsed["device"],
            session=parsed["session"],
            sessions_total=parsed["sessions_total"],
            recording=recording,
            stage=parsed["stage"],
            progress=parsed["progress"],
            detail=recording or hint_detail,
            pipeline=parsed["pipeline"],
            steps=steps,
            elapsed_seconds=_process_elapsed_seconds(pid),
            owner_pid=pid,
        )

    return PipelineStatus(
        state=STATE_PROCESSING,
        device=hint_device,
        stage=Stage.PROCESSING,
        detail=hint_detail,
        elapsed_seconds=_process_elapsed_seconds(pid),
        owner_pid=pid,
    )


def _cli_pipeline_hint(pid: int) -> tuple[str, Optional[str]]:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "CLI pipeline running", None
    command = completed.stdout.strip()
    if "--reprocess" in command:
        label = "Reprocessing archive"
    elif "--retry-failed" in command:
        label = "Retrying failed sessions"
    else:
        label = "Processing recordings"
    match = re.search(r"--source\s+(\S+)", command)
    device = Path(match.group(1)).name if match else None
    return label, device


def is_status_owned_by_other(
    path: Optional[Path] = None,
    *,
    my_pid: Optional[int] = None,
) -> bool:
    """True when another live process owns an in-flight pipeline status."""
    status_path = path or default_status_path()
    my_pid = my_pid if my_pid is not None else os.getpid()
    status = load_status(status_path)
    if status.state in (STATE_PROCESSING, STATE_SETTLING):
        owner = status.owner_pid
        if owner is not None and owner != my_pid and _pid_alive(owner):
            return True
    return any(pid != my_pid for pid in find_cli_pipeline_pids())


def resolve_display_status(status: PipelineStatus) -> PipelineStatus:
    """Upgrade idle/watching status when a CLI pipeline is running."""
    cli_pids = find_cli_pipeline_pids(exclude_pid=os.getpid())
    if cli_pids:
        enriched = _status_from_cli_pipeline(cli_pids[0])
        if enriched is not None:
            return enriched
    if status.state not in (STATE_IDLE, STATE_WATCHING):
        return status
    return status


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
        self._owner_pid = os.getpid()
        self._status = PipelineStatus()
        self._run_started_at: Optional[float] = None
        self._step_ids: List[str] = []
        self._lock = threading.RLock()
        self._active_sessions = 0

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
                self._status.started_at = _utc_now()
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
            started_at=_utc_now(),
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
                elif step.status == STEP_ACTIVE:
                    step.status = STEP_DONE
            if detail is not None:
                self._status.detail = detail
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
        self._write()

    def skip_step(self, step_id: str) -> None:
        with self._lock:
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
        with self._lock:
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