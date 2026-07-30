"""Operator health check — services, tools, keys, layout, failures."""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ideaforge import __version__
from ideaforge.archive_status import pending_failure_count, retry_failed_hint
from ideaforge.config import (
    IdeaForgeConfig,
    has_anthropic_api_key,
    has_xai_api_key,
)
from ideaforge.config_validate import (
    ConfigValidationError,
    collect_runtime_warnings,
    validate_config,
    validate_config_file,
)
from ideaforge.device_registry import list_device_archive_roots
from ideaforge.health import (
    DAEMON_LOG_PATH,
    check_daemon_health,
    check_menubar_health,
)
from ideaforge.status import default_status_path, load_last_notes


@dataclass
class DoctorCheck:
    name: str
    status: str  # ok | warn | error | info
    detail: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class DoctorReport:
    version: str
    ok: bool
    checks: List[DoctorCheck] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "ok": self.ok,
            "checks": [c.to_dict() for c in self.checks],
            "warnings": self.warnings,
            "errors": self.errors,
        }


def _tool_path(name: str) -> Optional[str]:
    return shutil.which(name)


def _config_layout_hint(cfg: IdeaForgeConfig) -> str:
    archive = cfg.archive.expanduser()
    if not archive.exists():
        return f"archive not created yet ({archive})"
    if cfg.devices:
        names = ", ".join(d.name for d in cfg.devices)
        return f"per-device roots under {archive} ({names})"
    # Peek for session packages vs flat date folders
    date_dirs = [
        p
        for p in archive.iterdir()
        if p.is_dir() and len(p.name) == 10 and p.name[4] == "-"
    ][:5]
    if not date_dirs:
        # maybe device subdirs without [[devices]]
        sub = [p for p in archive.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if sub:
            return f"archive has subfolders (check [[devices]] or flat layout): {archive}"
        return f"empty archive root {archive}"
    nested = 0
    for date_dir in date_dirs:
        for child in date_dir.iterdir():
            if child.is_dir() and child.name.startswith("R20"):
                nested += 1
                break
    if nested:
        return f"session packages under date folders ({nested}/{len(date_dirs)} sampled have R…/)"
    return f"flat or notes-at-root date folders under {archive}"


def run_doctor(cfg: IdeaForgeConfig, *, config_path: Optional[Path] = None) -> DoctorReport:
    """Build a doctor report for the given config."""
    checks: List[DoctorCheck] = []
    warnings: List[str] = []
    errors: List[str] = []

    path = config_path or cfg.default_config_path()
    if path.is_file():
        try:
            loaded = validate_config_file(path, check_paths=True, check_runtime=False)
            cfg = loaded
            checks.append(
                DoctorCheck("config", "ok", f"valid — {path}")
            )
        except ConfigValidationError as exc:
            errors.append(str(exc).strip())
            checks.append(DoctorCheck("config", "error", f"invalid — {path}"))
    else:
        try:
            validate_config(cfg, check_paths=True)
            checks.append(
                DoctorCheck(
                    "config",
                    "warn",
                    f"no config file at {path} — using defaults",
                )
            )
            warnings.append(f"Config file missing: {path}")
        except ConfigValidationError as exc:
            errors.append(str(exc).strip())
            checks.append(DoctorCheck("config", "error", "defaults invalid"))

    for item in collect_runtime_warnings(cfg):
        warnings.append(item)
        checks.append(DoctorCheck("runtime", "warn", item))

    ffmpeg = _tool_path("ffmpeg")
    checks.append(
        DoctorCheck(
            "ffmpeg",
            "ok" if ffmpeg else "warn",
            ffmpeg or "not found on PATH",
        )
    )
    rsync = _tool_path("rsync")
    checks.append(
        DoctorCheck(
            "rsync",
            "ok" if rsync else ("warn" if cfg.sync_enabled else "info"),
            rsync or "not found on PATH",
        )
    )

    if has_xai_api_key():
        checks.append(DoctorCheck("XAI_API_KEY", "ok", "set in environment"))
    else:
        checks.append(DoctorCheck("XAI_API_KEY", "info", "not set (Ollama fallback for auto)"))

    if has_anthropic_api_key():
        checks.append(DoctorCheck("ANTHROPIC_API_KEY", "ok", "set in environment"))
    else:
        checks.append(DoctorCheck("ANTHROPIC_API_KEY", "info", "not set"))

    hf = (
        (cfg.hf_token or "").strip()
        or (os.environ.get("HF_TOKEN") or "").strip()
        or (os.environ.get("HUGGINGFACE_TOKEN") or "").strip()
    )
    if hf:
        checks.append(DoctorCheck("HF_TOKEN", "ok", "set"))
    else:
        status = "warn" if cfg.diarize else "info"
        checks.append(
            DoctorCheck(
                "HF_TOKEN",
                status,
                "not set" + (" (needed for diarize)" if cfg.diarize else ""),
            )
        )

    if platform.system() == "Darwin":
        daemon = check_daemon_health()
        menubar = check_menubar_health()
        checks.append(
            DoctorCheck(
                "daemon",
                "ok" if daemon.running else ("warn" if daemon.installed else "error"),
                daemon.status_line,
            )
        )
        if not daemon.installed:
            errors.append("Daemon LaunchAgent not installed — run ./scripts/install-daemon.sh")
        checks.append(
            DoctorCheck(
                "menubar",
                "ok" if menubar.running else ("warn" if menubar.installed else "info"),
                menubar.status_line,
            )
        )
    else:
        checks.append(
            DoctorCheck("daemon", "info", "LaunchAgent checks are macOS only")
        )

    archive = cfg.archive.expanduser()
    checks.append(
        DoctorCheck(
            "archive",
            "ok" if archive.exists() else "warn",
            str(archive),
        )
    )
    checks.append(DoctorCheck("layout", "info", _config_layout_hint(cfg)))

    fail_count = pending_failure_count(cfg)
    if fail_count:
        checks.append(
            DoctorCheck(
                "failures",
                "warn",
                f"{fail_count} pending — retry: {retry_failed_hint(cfg)}",
            )
        )
        warnings.append(f"{fail_count} pending failed session(s)")
    else:
        checks.append(DoctorCheck("failures", "ok", "none pending"))

    notes = load_last_notes()
    if notes:
        checks.append(
            DoctorCheck(
                "last_notes",
                "ok",
                f"{len(notes)} link(s) — {notes[0].title}",
            )
        )
    else:
        checks.append(DoctorCheck("last_notes", "info", "no recent notes recorded"))

    checks.append(
        DoctorCheck("status_json", "info", str(default_status_path()))
    )
    checks.append(DoctorCheck("daemon_log", "info", str(DAEMON_LOG_PATH)))
    checks.append(DoctorCheck("python", "info", platform.python_version()))
    checks.append(DoctorCheck("platform", "info", platform.platform()))

    roots = list_device_archive_roots(cfg)
    if len(roots) > 1:
        checks.append(
            DoctorCheck(
                "devices",
                "info",
                f"{len(roots)} archive roots: " + ", ".join(n for n, _ in roots),
            )
        )

    ok = not errors
    return DoctorReport(
        version=__version__,
        ok=ok,
        checks=checks,
        warnings=warnings,
        errors=errors,
    )


def format_doctor_report(report: DoctorReport) -> str:
    lines = [
        f"IdeaForge v{report.version} doctor",
        "─" * 40,
        "",
    ]
    icons = {"ok": "✓", "warn": "⚠", "error": "✗", "info": "·"}
    for check in report.checks:
        icon = icons.get(check.status, "·")
        lines.append(f"  {icon} {check.name}: {check.detail}")

    lines.append("")
    if report.errors:
        lines.append("Errors:")
        for err in report.errors:
            for part in str(err).splitlines():
                lines.append(f"  ✗ {part.strip()}")
        lines.append("")
    if report.warnings and not any(c.status == "warn" for c in report.checks):
        lines.append("Warnings:")
        for warn in report.warnings:
            lines.append(f"  ⚠ {warn}")
        lines.append("")

    if report.ok:
        lines.append("Result: OK (warnings above are non-fatal)")
    else:
        lines.append("Result: NEEDS ATTENTION")
    return "\n".join(lines)


def print_doctor_report(
    cfg: IdeaForgeConfig,
    *,
    config_path: Optional[Path] = None,
    as_json: bool = False,
) -> int:
    """Print doctor report; return 0 if ok, 1 if hard errors."""
    report = run_doctor(cfg, config_path=config_path)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_doctor_report(report))
    return 0 if report.ok else 1
