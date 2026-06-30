"""Optional rsync hook to push archives to a remote target after notes are generated."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

SyncScope = Literal["session", "device", "archive"]


@dataclass
class SyncSettings:
    enabled: bool = False
    target: str = ""
    after_notes: bool = True
    scope: SyncScope = "session"
    extra_args: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.extra_args is None:
            self.extra_args = ["-az"]


@dataclass
class SyncResult:
    ok: bool
    local_path: str
    target: str
    skipped: bool = False
    reason: Optional[str] = None


def rsync_available() -> bool:
    return shutil.which("rsync") is not None


def default_sync_log_path(archive_root: Path) -> Path:
    return archive_root / ".sync_log.json"


def load_sync_log(archive_root: Path) -> Dict[str, Any]:
    path = default_sync_log_path(archive_root)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"synced": {}}


def save_sync_log(archive_root: Path, log: Dict[str, Any]) -> None:
    path = default_sync_log_path(archive_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def _sync_key(local_path: Path, target: str) -> str:
    return f"{local_path.resolve()}|{target}"


def resolve_sync_paths(
    *,
    work_folder: Path,
    archive_root: Path,
    device_root: Path,
    scope: SyncScope,
) -> Path:
    if scope == "session":
        return work_folder
    if scope == "device":
        return device_root
    return archive_root


def run_rsync(
    local_path: Path,
    settings: SyncSettings,
    *,
    dry_run: bool = False,
) -> SyncResult:
    if not settings.enabled:
        return SyncResult(
            ok=True,
            local_path=str(local_path),
            target=settings.target,
            skipped=True,
            reason="sync disabled",
        )
    if not settings.target.strip():
        return SyncResult(
            ok=False,
            local_path=str(local_path),
            target="",
            skipped=True,
            reason="sync.target not configured",
        )
    if not rsync_available():
        return SyncResult(
            ok=False,
            local_path=str(local_path),
            target=settings.target,
            skipped=True,
            reason="rsync not found on PATH",
        )
    if not local_path.exists():
        return SyncResult(
            ok=False,
            local_path=str(local_path),
            target=settings.target,
            skipped=True,
            reason="local path missing",
        )

    destination = settings.target.rstrip("/") + "/"
    extra = list(settings.extra_args)
    if dry_run and "-n" not in extra and "--dry-run" not in extra:
        extra = ["-n", *extra]
    cmd = ["rsync", *extra, str(local_path) + "/", destination]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        return SyncResult(
            ok=False,
            local_path=str(local_path),
            target=settings.target,
            reason=err[:500],
        )

    _ = completed
    return SyncResult(ok=True, local_path=str(local_path), target=settings.target)


def maybe_sync_after_notes(
    *,
    work_folder: Path,
    archive_root: Path,
    device_root: Path,
    session_stem: str,
    settings: SyncSettings,
    force: bool = False,
) -> SyncResult:
    """Push archive data to remote target when configured."""
    if not settings.enabled or not settings.after_notes:
        return SyncResult(
            ok=True,
            local_path=str(work_folder),
            target=settings.target,
            skipped=True,
            reason="after_notes sync disabled",
        )

    summary_json = work_folder / f"{session_stem}_summary.json"
    summary_md = work_folder / f"{session_stem}_summary.md"
    if not summary_json.exists() and not summary_md.exists():
        return SyncResult(
            ok=True,
            local_path=str(work_folder),
            target=settings.target,
            skipped=True,
            reason="no summary output yet",
        )

    local_path = resolve_sync_paths(
        work_folder=work_folder,
        archive_root=archive_root,
        device_root=device_root,
        scope=settings.scope,
    )
    log = load_sync_log(archive_root)
    key = _sync_key(local_path, settings.target)
    if not force and key in log.get("synced", {}):
        return SyncResult(
            ok=True,
            local_path=str(local_path),
            target=settings.target,
            skipped=True,
            reason="already synced",
        )

    result = run_rsync(local_path, settings)
    if result.ok and not result.skipped:
        log.setdefault("synced", {})[key] = {
            "local_path": str(local_path),
            "target": settings.target,
            "session_stem": session_stem,
            "synced_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_sync_log(archive_root, log)
        print(f"   ☁️  Synced {local_path.name} → {settings.target}")
    elif result.reason and not result.ok:
        print(f"   ⚠️  Remote sync failed: {result.reason}")
    return result