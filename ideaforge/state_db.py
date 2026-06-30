"""Versioned archive state for ``.processed_log.json``."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Set, TypedDict, Union

PROCESSED_LOG_SCHEMA_VERSION = 1
PROCESSED_LOG_FILENAME = ".processed_log.json"


class ProcessedFileEntry(TypedDict):
    source: str
    archive: str
    processed_at: str


class SessionFailureEntry(TypedDict, total=False):
    session_stem: str
    archive_folder: str
    archive_files: List[str]
    chunk_hashes: List[str]
    error: str
    pipeline: str
    failed_at: str


class ProcessedLog(TypedDict):
    schema_version: int
    hashes: List[str]
    files: Dict[str, ProcessedFileEntry]
    failures: Dict[str, SessionFailureEntry]


def empty_processed_log() -> ProcessedLog:
    return {
        "schema_version": PROCESSED_LOG_SCHEMA_VERSION,
        "hashes": [],
        "files": {},
        "failures": {},
    }


def _coerce_processed_log(raw: MutableMapping[str, Any]) -> ProcessedLog:
    if "hashes" not in raw:
        raw["hashes"] = []
    if "files" not in raw:
        raw["files"] = {}
    if "failures" not in raw:
        raw["failures"] = {}
    raw["schema_version"] = int(raw.get("schema_version", 0))
    return raw  # type: ignore[return-value]


def migrate_processed_log(raw: MutableMapping[str, Any]) -> ProcessedLog:
    """Upgrade legacy logs to the current schema version."""
    log = _coerce_processed_log(raw)
    version = log["schema_version"]

    if version < 1:
        for entry in log["failures"].values():
            if "failed_at" not in entry:
                entry["failed_at"] = datetime.now().isoformat(timespec="seconds")
        log["schema_version"] = 1

    if log["schema_version"] > PROCESSED_LOG_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported processed log schema version {log['schema_version']} "
            f"(max supported {PROCESSED_LOG_SCHEMA_VERSION})"
        )

    return log


def normalize_processed_log(log: MutableMapping[str, Any]) -> ProcessedLog:
    """Ensure expected keys exist and apply migrations."""
    return migrate_processed_log(log)


def load_processed_log(archive: Path) -> ProcessedLog:
    log_path = archive / PROCESSED_LOG_FILENAME
    if log_path.exists():
        try:
            raw = json.loads(log_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return normalize_processed_log(raw)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            pass
    return empty_processed_log()


def save_processed_log(archive: Path, log: ProcessedLog) -> None:
    log_path = archive / PROCESSED_LOG_FILENAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = normalize_processed_log(log)
    payload["schema_version"] = PROCESSED_LOG_SCHEMA_VERSION
    log_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def record_session_failure(
    log: MutableMapping[str, Any],
    *,
    session_stem: str,
    archive_folder: Path,
    archive_files: List[Path],
    chunk_hashes: List[str],
    error: str,
    pipeline: str,
) -> None:
    normalized = normalize_processed_log(log)
    normalized["failures"][session_stem] = {
        "session_stem": session_stem,
        "archive_folder": str(archive_folder),
        "archive_files": [str(path) for path in archive_files],
        "chunk_hashes": chunk_hashes,
        "error": error,
        "pipeline": pipeline,
        "failed_at": datetime.now().isoformat(timespec="seconds"),
    }


def clear_session_failure(log: MutableMapping[str, Any], session_stem: str) -> None:
    normalized = normalize_processed_log(log)
    normalized["failures"].pop(session_stem, None)


def failed_session_stems(log: MutableMapping[str, Any]) -> Set[str]:
    return set(normalize_processed_log(log).get("failures", {}).keys())


ProcessedLogLike = Union[ProcessedLog, MutableMapping[str, Any]]