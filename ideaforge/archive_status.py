"""Aggregate failures and queues across per-device archive roots."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from ideaforge.config import IdeaForgeConfig
from ideaforge.device_registry import list_device_archive_roots
from ideaforge.ingest import failed_session_stems, load_processed_log


def _failure_label(device_name: str, session_stem: str, *, multi_device: bool) -> str:
    if multi_device:
        return f"{device_name}/{session_stem}"
    return session_stem


def collect_archive_failures(cfg: IdeaForgeConfig) -> Tuple[List[str], Dict[str, Any], List[Dict[str, Any]]]:
    """
    Return aggregated failure labels, merged failure details, and per-device summaries.

    When ``[[devices]]`` is configured, failure labels are prefixed ``device/stem``.
    """
    multi_device = bool(cfg.devices)
    labels: List[str] = []
    details: Dict[str, Any] = {}
    devices: List[Dict[str, Any]] = []

    for device_name, archive_root in list_device_archive_roots(cfg):
        processed_log = load_processed_log(archive_root)
        stems = sorted(failed_session_stems(processed_log))
        failure_map = processed_log.get("failures", {})
        devices.append({
            "name": device_name,
            "archive_root": str(archive_root),
            "failure_count": len(stems),
            "failures": stems,
        })
        for stem in stems:
            label = _failure_label(device_name, stem, multi_device=multi_device)
            labels.append(label)
            entry = failure_map.get(stem)
            if entry is not None:
                details[label] = dict(entry)

    return sorted(labels), details, devices


def pending_failure_count(cfg: IdeaForgeConfig) -> int:
    """Total pending failed sessions across all configured device archives."""
    return sum(device["failure_count"] for device in collect_archive_failures(cfg)[2])


def retry_failed_hint(cfg: IdeaForgeConfig) -> str:
    archive = cfg.archive.expanduser()
    if cfg.devices and len(cfg.devices) == 1:
        device_root = archive / cfg.devices[0].name
        return f"ideaforge --source {device_root} --retry-failed"
    if cfg.devices:
        return f"ideaforge fleet   # per-device roots under {archive}"
    return f"ideaforge --source {archive} --retry-failed"