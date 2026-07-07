"""Human-friendly meeting note filenames (YYYYMMDD - description.md)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

from ideaforge.session_time import RECORDING_STEM_PATTERN, parse_recording_timestamp

DATE_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INVALID_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')
WHITESPACE_RE = re.compile(r"\s+")
DEFAULT_DESCRIPTION_MAX = 60
LEGACY_SUMMARY_MD_SUFFIX = "_summary.md"


def _truncate_at_word(text: str, max_length: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_length:
        return cleaned
    cut = cleaned[: max_length + 1]
    if " " in cut:
        return cut.rsplit(" ", 1)[0].rstrip(".,;:-")
    return cleaned[:max_length].rstrip(".,;:-")


def sanitize_filename_component(text: str) -> str:
    """Make a string safe for macOS filenames."""
    cleaned = text.replace(":", " - ")
    cleaned = INVALID_FILENAME_CHARS.sub(" ", cleaned)
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip(" .")
    return cleaned


def iso_date_to_prefix(iso_date: str) -> Optional[str]:
    """Convert ``YYYY-MM-DD`` to sortable ``YYYYMMDD``."""
    value = iso_date.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return None


def date_prefix_for_session(
    *,
    iso_date: str = "",
    session_stem: str = "",
    folder: Optional[Path] = None,
) -> str:
    """Resolve ``YYYYMMDD`` for summary filenames."""
    for candidate in (iso_date,):
        prefix = iso_date_to_prefix(candidate)
        if prefix:
            return prefix

    if session_stem:
        parsed = parse_recording_timestamp(Path(session_stem))
        if parsed is not None:
            return parsed.strftime("%Y%m%d")

    if folder is not None and DATE_FOLDER_RE.match(folder.name):
        prefix = iso_date_to_prefix(folder.name)
        if prefix:
            return prefix

    return datetime.now().strftime("%Y%m%d")


def recording_description_for_filename(
    *,
    title: str,
    session_stem: str = "",
    action_preview: Optional[Sequence[str]] = None,
    max_length: int = DEFAULT_DESCRIPTION_MAX,
) -> str:
    """
    Short label for filenames — mirrors notification subtitle/message.

    Uses the meeting title when present; falls back to action-item previews
    (the notification message line) when the title is missing or generic.
    """
    label = (title or "").strip()
    generic = not label or label == session_stem
    if generic and action_preview:
        label = " · ".join(item.strip() for item in action_preview if item.strip())
    if not label:
        label = session_stem or "Meeting notes"
    sanitized = sanitize_filename_component(label)
    return _truncate_at_word(sanitized, max_length)


def friendly_summary_md_filename(*, date_prefix: str, description: str) -> str:
    """Build ``YYYYMMDD - description.md``."""
    return f"{date_prefix} - {description}.md"


def legacy_summary_md_path(folder: Path, session_stem: str) -> Path:
    return folder / f"{session_stem}{LEGACY_SUMMARY_MD_SUFFIX}"


def _summary_md_from_json_metadata(json_path: Path) -> Optional[Path]:
    if not json_path.is_file():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, Mapping):
        return None
    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    md_name = metadata.get("summary_md")
    if not isinstance(md_name, str) or not md_name.strip():
        return None
    candidate = json_path.parent / md_name
    return candidate if candidate.is_file() else None


def resolve_summary_md_path(folder: Path, session_stem: str) -> Optional[Path]:
    """Locate the markdown summary for a session (friendly or legacy name)."""
    from_metadata = _summary_md_from_json_metadata(folder / f"{session_stem}_summary.json")
    if from_metadata is not None:
        return from_metadata

    legacy = legacy_summary_md_path(folder, session_stem)
    if legacy.is_file():
        return legacy
    return None


def summary_md_exists(folder: Path, session_stem: str) -> bool:
    return resolve_summary_md_path(folder, session_stem) is not None


def action_preview_lines(action_items: Sequence[Any]) -> List[str]:
    """Build notification-style action previews from structured action items."""
    previews: List[str] = []
    for item in action_items[:2]:
        if isinstance(item, Mapping):
            who = str(item.get("who", "TBD")).strip() or "TBD"
            what = str(item.get("what", "")).strip()
        else:
            who = getattr(item, "who", "TBD") or "TBD"
            what = getattr(item, "what", "") or ""
        if what:
            previews.append(f"{who}: {what}")
    return previews


def allocate_summary_md_path(folder: Path, filename: str) -> Path:
    """Return a non-colliding path for a new summary markdown file."""
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    for index in range(2, 100):
        alt = folder / f"{stem} ({index}).md"
        if not alt.exists():
            return alt
    return folder / f"{stem} ({datetime.now().strftime('%H%M%S')}).md"


def refresh_friendly_summary_markdown(json_path: Path) -> Optional[Path]:
    """
    Rename an existing summary markdown file to the friendly ``YYYYMMDD - title.md``
    format using metadata already stored in the JSON sidecar.
    """
    if not json_path.is_file() or not json_path.name.endswith("_summary.json"):
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, Mapping):
        return None

    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    session_stem = str(metadata.get("session_stem") or "").strip()
    if not session_stem:
        session_stem = json_path.stem[: -len("_summary")]

    existing_md = resolve_summary_md_path(json_path.parent, session_stem)
    if existing_md is None or not existing_md.is_file():
        return None

    target = plan_summary_md_path(
        folder=json_path.parent,
        session_stem=session_stem,
        title=str(data.get("title", "")),
        iso_date=str(data.get("date") or metadata.get("recording_date", "")),
        action_preview=action_preview_lines(data.get("action_items", [])),
    )

    if target.resolve() != existing_md.resolve():
        target.write_text(existing_md.read_text(encoding="utf-8"), encoding="utf-8")
        existing_md.unlink()

    updated_metadata = dict(metadata)
    updated_metadata["session_stem"] = session_stem
    updated_metadata["summary_md"] = target.name
    data["metadata"] = updated_metadata
    json_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return target


def refresh_summaries_in_folder(folder: Path) -> List[Path]:
    """Apply friendly markdown names for every ``*_summary.json`` in ``folder``."""
    renamed: List[Path] = []
    for json_path in sorted(folder.glob("*_summary.json")):
        target = refresh_friendly_summary_markdown(json_path)
        if target is not None:
            renamed.append(target)
    return renamed


def plan_summary_md_path(
    *,
    folder: Path,
    session_stem: str,
    title: str,
    iso_date: str = "",
    action_preview: Optional[Sequence[str]] = None,
    max_description: int = DEFAULT_DESCRIPTION_MAX,
) -> Path:
    """Compute the markdown output path for a completed summary."""
    date_prefix = date_prefix_for_session(
        iso_date=iso_date,
        session_stem=session_stem,
        folder=folder,
    )
    description = recording_description_for_filename(
        title=title,
        session_stem=session_stem,
        action_preview=action_preview,
        max_length=max_description,
    )
    filename = friendly_summary_md_filename(
        date_prefix=date_prefix,
        description=description,
    )
    return allocate_summary_md_path(folder, filename)