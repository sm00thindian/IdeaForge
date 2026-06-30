"""Manual ``ideaforge sync`` command."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

from ideaforge.config import IdeaForgeConfig
from datetime import datetime

from ideaforge.device_registry import list_device_archive_roots
from ideaforge.remote_sync import (
    SyncScope,
    SyncSettings,
    _sync_key,
    load_sync_log,
    resolve_sync_paths,
    run_rsync,
    save_sync_log,
)

_DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _detect_sync_scope(source: Path, cfg: IdeaForgeConfig) -> SyncScope:
    resolved = source.expanduser().resolve()
    archive = cfg.archive.expanduser().resolve()
    if resolved == archive:
        return "archive"
    for _name, device_root in list_device_archive_roots(cfg):
        if resolved == device_root.resolve():
            return "device"
        if resolved.parent == device_root.resolve() and _DATE_FOLDER.match(resolved.name):
            return "session"
    if _DATE_FOLDER.match(resolved.name):
        return "session"
    if resolved.parent == archive:
        return "device"
    return "session"


def resolve_manual_sync(
    source: Path,
    cfg: IdeaForgeConfig,
    *,
    scope: Optional[SyncScope] = None,
) -> Tuple[Path, Path, Path, SyncScope]:
    """Return local rsync path, archive log root, device root, and effective scope."""
    resolved = source.expanduser().resolve()
    archive = cfg.archive.expanduser().resolve()
    effective_scope = scope or _detect_sync_scope(resolved, cfg)

    if effective_scope == "archive":
        return archive, archive, archive, effective_scope

    if effective_scope == "device":
        for name, device_root in list_device_archive_roots(cfg):
            if resolved == device_root.resolve() or (
                resolved.parent == archive and resolved.name == name
            ):
                return device_root, archive, device_root, effective_scope
        if resolved.parent == archive:
            return resolved, archive, resolved, effective_scope
        return resolved, archive, resolved, effective_scope

    # session scope
    if _DATE_FOLDER.match(resolved.name):
        work_folder = resolved
    elif _DATE_FOLDER.match(resolved.parent.name):
        work_folder = resolved.parent
    else:
        work_folder = resolved

    device_root = work_folder.parent
    device_name = None
    for name, root in list_device_archive_roots(cfg):
        if work_folder.parent == root.resolve():
            device_name = name
            device_root = root
            break
    if device_name is None and work_folder.parent == archive:
        device_root = archive

    local_path = resolve_sync_paths(
        work_folder=work_folder,
        archive_root=archive,
        device_root=device_root,
        scope="session",
    )
    return local_path, archive, device_root, effective_scope


def run_manual_sync(
    cfg: IdeaForgeConfig,
    source: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    scope: Optional[SyncScope] = None,
    target: Optional[str] = None,
) -> int:
    """Push archive data to a remote rsync target. Returns process exit code."""
    sync_target = (target or cfg.sync_target).strip()
    if not sync_target:
        print("❌ sync.target not configured — set [sync] in config.toml or pass --target")
        return 1

    local_path, archive_root, device_root, effective_scope = resolve_manual_sync(
        source,
        cfg,
        scope=scope,
    )
    if not local_path.exists():
        print(f"❌ Sync path not found: {local_path}")
        return 1

    settings = SyncSettings(
        enabled=True,
        target=sync_target,
        after_notes=True,
        scope=effective_scope,
        extra_args=list(cfg.sync_extra_args),
    )

    log = load_sync_log(archive_root)
    key = _sync_key(local_path, settings.target)
    if not force and not dry_run and key in log.get("synced", {}):
        print(f"↳ Already synced (use --force to repeat): {local_path}")
        return 0

    mode = "dry-run" if dry_run else "sync"
    print(f"☁️  {mode}: {local_path} → {settings.target} (scope={effective_scope})")
    result = run_rsync(local_path, settings, dry_run=dry_run)
    if not result.ok:
        print(f"❌ Sync failed: {result.reason or 'unknown error'}")
        return 1

    if dry_run:
        print("✓ Dry-run complete (no files transferred)")
        return 0

    log.setdefault("synced", {})[key] = {
        "local_path": str(local_path),
        "target": settings.target,
        "session_stem": local_path.name,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "manual": True,
    }
    save_sync_log(archive_root, log)
    print(f"✓ Synced {local_path.name} → {settings.target}")
    return 0