"""CLI pipeline process discovery and display status enrichment."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ideaforge.status_model import (
    STATE_IDLE,
    STATE_PROCESSING,
    STATE_SETTLING,
    STATE_WATCHING,
    STEP_ACTIVE,
    STEP_DONE,
    STEP_PENDING,
    Stage,
    StatusStep,
    StepId,
    StepLabel,
    PipelineStatus,
    default_status_path,
    load_status,
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



