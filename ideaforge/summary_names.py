"""Human-friendly meeting note filenames (YYYYMMDD - description.md)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

from ideaforge.session_time import (
    RECORDING_STEM_PATTERN,
    is_plausible_recording_time,
    parse_recording_timestamp,
)

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
    """Resolve ``YYYYMMDD`` for summary filenames.

    Prefers explicit ISO date, then a plausible filename stem, then the archive
    date folder. Implausible stem years (device default-era) are ignored so
    notes do not become ``20141006 - ….md``.
    """
    folder_dt: Optional[datetime] = None
    if folder is not None and DATE_FOLDER_RE.match(folder.name):
        try:
            folder_dt = datetime.strptime(folder.name, "%Y-%m-%d")
        except ValueError:
            folder_dt = None

    for candidate in (iso_date,):
        prefix = iso_date_to_prefix(candidate)
        if not prefix:
            continue
        try:
            candidate_dt = datetime.strptime(candidate.strip(), "%Y-%m-%d")
        except ValueError:
            return prefix
        # Trust explicit ISO unless it is absurd vs the archive folder.
        if folder_dt is None or is_plausible_recording_time(
            candidate_dt, reference=folder_dt
        ):
            return prefix

    if session_stem:
        parsed = parse_recording_timestamp(Path(session_stem))
        if parsed is not None:
            ref = folder_dt or datetime.now()
            if is_plausible_recording_time(parsed, reference=ref):
                return parsed.strftime("%Y%m%d")

    if folder_dt is not None:
        prefix = iso_date_to_prefix(folder.name)
        if prefix:
            return prefix

    return datetime.now().strftime("%Y%m%d")


def recording_description_for_filename(
    *,
    title: str,
    session_stem: str = "",
    action_preview: Optional[Sequence[str]] = None,
    output_intent: Optional[str] = None,
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
        label = session_stem or (
            "Song idea" if output_intent == "song_idea" else "Meeting notes"
        )
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
    # Filename only (preferred) or relative path; also check parent date folder
    # when JSON lives in a nested session package.
    name = Path(md_name).name
    candidates = [
        json_path.parent / md_name,
        json_path.parent / name,
        json_path.parent.parent / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _summary_json_candidates(folder: Path, session_stem: str) -> List[Path]:
    """Possible locations for ``{stem}_summary.json`` (nested or flat)."""
    return [
        folder / f"{session_stem}_summary.json",
        folder / session_stem / f"{session_stem}_summary.json",
        folder.parent / f"{session_stem}_summary.json",
    ]


def resolve_summary_md_path(folder: Path, session_stem: str) -> Optional[Path]:
    """Locate the markdown summary for a session (friendly or legacy name).

    Notes may live in the date-folder root while JSON lives in a session
    subfolder (or both may still be flat under the date folder).
    """
    for json_path in _summary_json_candidates(folder, session_stem):
        from_metadata = _summary_md_from_json_metadata(json_path)
        if from_metadata is not None:
            return from_metadata

    search_dirs = [folder]
    # Nested session package → also search date folder (parent).
    if DATE_FOLDER_RE.match(folder.parent.name):
        search_dirs.append(folder.parent)
    # Date folder → also search nested session package.
    nested = folder / session_stem
    if nested.is_dir():
        search_dirs.append(nested)

    for directory in search_dirs:
        legacy = legacy_summary_md_path(directory, session_stem)
        if legacy.is_file():
            return legacy
    return None


def summary_md_exists(folder: Path, session_stem: str) -> bool:
    return resolve_summary_md_path(folder, session_stem) is not None


def creative_preview_lines(data: Mapping[str, Any]) -> List[str]:
    """Build notification-style previews from creative summary JSON."""
    hook = str(data.get("chorus_hook") or "").strip()
    if hook:
        return [hook[:80]]
    themes = data.get("themes") or []
    if isinstance(themes, list) and themes:
        return [str(t).strip() for t in themes[:2] if str(t).strip()]
    summary = str(data.get("creative_summary") or "").strip()
    if summary:
        return [summary[:80]]
    return ["Song idea"]


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

    Target folder is the date-folder root when the JSON lives in a session package.
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

    notes_folder = json_path.parent
    if DATE_FOLDER_RE.match(json_path.parent.parent.name):
        notes_folder = json_path.parent.parent

    target = plan_summary_md_path(
        folder=notes_folder,
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
    """Apply friendly markdown names for every ``*_summary.json`` under ``folder``."""
    from ideaforge.session_layout import iter_summary_json_files

    renamed: List[Path] = []
    for json_path in iter_summary_json_files(folder):
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
    output_intent: Optional[str] = None,
    max_description: int = DEFAULT_DESCRIPTION_MAX,
) -> Path:
    """Compute the markdown output path for a completed summary.

    ``folder`` should be the **notes directory** (date-folder root for nested
    session packages).
    """
    # Prefer date-folder name when given a nested session dir.
    date_folder = folder
    if not DATE_FOLDER_RE.match(folder.name) and DATE_FOLDER_RE.match(folder.parent.name):
        date_folder = folder.parent

    date_prefix = date_prefix_for_session(
        iso_date=iso_date,
        session_stem=session_stem,
        folder=date_folder,
    )
    description = recording_description_for_filename(
        title=title,
        session_stem=session_stem,
        action_preview=action_preview,
        output_intent=output_intent,
        max_length=max_description,
    )
    filename = friendly_summary_md_filename(
        date_prefix=date_prefix,
        description=description,
    )
    return allocate_summary_md_path(date_folder, filename)