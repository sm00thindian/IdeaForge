"""Service health checks and `ideaforge --status` reporting."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ideaforge import __version__
from ideaforge.config import IdeaForgeConfig
from ideaforge.device import find_recorder_mounts
from ideaforge.ingest import failed_session_stems, load_processed_log
from ideaforge.status import (
    STATE_COMPLETE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PROCESSING,
    STATE_SETTLING,
    STATE_WATCHING,
    PipelineStatus,
    default_status_path,
    format_elapsed,
    load_status,
)

DAEMON_LABEL = "com.ideaforge.daemon"
MENUBAR_LABEL = "com.ideaforge.menubar"
MENUBAR_LOCK_PATH = Path.home() / "Library/Application Support/IdeaForge/menubar.lock"
DAEMON_LOG_PATH = Path.home() / "Library" / "Logs" / "ideaforge" / "daemon.log"

_STATE_LABELS = {
    STATE_IDLE: "Idle",
    STATE_WATCHING: "Watching for recorder",
    STATE_SETTLING: "Waiting for mount to settle",
    STATE_PROCESSING: "Processing",
    STATE_COMPLETE: "Complete",
    STATE_ERROR: "Error",
}


@dataclass
class ServiceHealth:
    label: str
    installed: bool
    running: bool
    pid: Optional[int] = None

    @property
    def status_line(self) -> str:
        if not self.installed:
            return "not installed"
        if self.running:
            pid_hint = f" (pid {self.pid})" if self.pid else ""
            return f"running{pid_hint}"
        return "stopped (LaunchAgent installed)"


def _is_darwin() -> bool:
    return platform.system() == "Darwin"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock_pid(lock_path: Path) -> Optional[int]:
    if not lock_path.is_file():
        return None
    try:
        return int(lock_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _pgrep_first(pattern: str) -> Optional[int]:
    if not _is_darwin():
        return None
    try:
        completed = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        return int(completed.stdout.strip().splitlines()[0])
    except ValueError:
        return None


def _launch_agent_installed(label: str) -> bool:
    plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    return plist.is_file()


def check_daemon_health() -> ServiceHealth:
    pid = _pgrep_first(r"run-daemon\.sh|ideaforge.*--daemon")
    return ServiceHealth(
        label=DAEMON_LABEL,
        installed=_launch_agent_installed(DAEMON_LABEL),
        running=pid is not None,
        pid=pid,
    )


def check_menubar_health() -> ServiceHealth:
    lock_pid = _read_lock_pid(MENUBAR_LOCK_PATH)
    if lock_pid is not None and _pid_alive(lock_pid):
        pid = lock_pid
    else:
        pid = _pgrep_first(r"ideaforge\.menubar_app|ideaforge-menubar|run-menubar\.sh")
    return ServiceHealth(
        label=MENUBAR_LABEL,
        installed=_launch_agent_installed(MENUBAR_LABEL),
        running=pid is not None,
        pid=pid,
    )


def _pipeline_lines(status: PipelineStatus) -> List[str]:
    headline = _STATE_LABELS.get(status.state, status.state.title())
    if status.stage and status.state == STATE_PROCESSING:
        headline = status.stage

    lines = [
        f"  State:      {headline}",
    ]
    if status.device:
        lines.append(f"  Device:     {status.device}")
    if status.detail:
        lines.append(f"  Detail:     {status.detail}")
    if status.progress is not None and status.state == STATE_PROCESSING:
        lines.append(f"  Progress:   {int(status.progress * 100)}%")
    elapsed = format_elapsed(status)
    if elapsed != "—":
        lines.append(f"  Elapsed:    {elapsed}")
    if status.sessions_total > 1 and status.session:
        lines.append(f"  Session:    {status.session}/{status.sessions_total}")
    if status.error:
        lines.append(f"  Error:      {status.error}")
    if status.updated_at:
        lines.append(f"  Updated:    {status.updated_at}")
    status_path = default_status_path()
    lines.append(f"  File:       {status_path}")
    return lines


def collect_status_snapshot(cfg: IdeaForgeConfig) -> Dict[str, Any]:
    archive = cfg.archive.expanduser().resolve()
    processed_log = load_processed_log(archive)
    failures = sorted(failed_session_stems(processed_log))
    failure_details = processed_log.get("failures", {})
    devices = find_recorder_mounts() if _is_darwin() else []

    pipeline = load_status()
    daemon = check_daemon_health()
    menubar = check_menubar_health()

    return {
        "version": __version__,
        "archive": str(archive),
        "pending_failures": failures,
        "failure_count": len(failures),
        "failures": failure_details,
        "pipeline": pipeline.to_dict(),
        "services": {
            "daemon": asdict(daemon),
            "menubar": asdict(menubar),
        },
        "recorders": [
            {
                "label": device.label,
                "mount_path": str(device.mount_path),
                "recording_count": device.recording_count,
            }
            for device in devices
        ],
        "paths": {
            "status_json": str(default_status_path()),
            "daemon_log": str(DAEMON_LOG_PATH),
            "menubar_lock": str(MENUBAR_LOCK_PATH),
        },
    }


def format_status_report(cfg: IdeaForgeConfig) -> str:
    snapshot = collect_status_snapshot(cfg)
    archive = Path(snapshot["archive"])
    pipeline = load_status()
    daemon = check_daemon_health()
    menubar = check_menubar_health()
    failures: List[str] = snapshot["pending_failures"]

    lines = [
        f"IdeaForge v{__version__} status",
        "─" * 40,
        "",
        "Pipeline (status.json)",
        *_pipeline_lines(pipeline),
        "",
        "Services",
        f"  Daemon:     {daemon.status_line}",
        f"  Menubar:    {menubar.status_line}",
        "",
        "Archive",
        f"  Path:       {archive}",
    ]

    if failures:
        preview = ", ".join(failures[:3])
        extra = f" (+{len(failures) - 3} more)" if len(failures) > 3 else ""
        lines.append(f"  Failures:   {len(failures)} pending — {preview}{extra}")
        lines.append("              Retry: ideaforge --source ~/IdeaForge --retry-failed")
    else:
        lines.append("  Failures:   none pending")

    recorders = snapshot["recorders"]
    lines.append("")
    lines.append("Recorder")
    if not recorders:
        lines.append("  Detected:   none")
    elif len(recorders) == 1:
        rec = recorders[0]
        lines.append(
            f"  Detected:   {rec['label']} "
            f"({rec['recording_count']} recording(s) at {rec['mount_path']})"
        )
    else:
        names = ", ".join(rec["label"] for rec in recorders)
        lines.append(f"  Detected:   {len(recorders)} devices — {names}")

    lines.extend([
        "",
        f"Log:        {DAEMON_LOG_PATH}",
    ])
    return "\n".join(lines)


def print_status_report(cfg: IdeaForgeConfig, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(collect_status_snapshot(cfg), indent=2, ensure_ascii=False))
        return
    print(format_status_report(cfg))