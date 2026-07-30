"""Last-run markdown notes links for the menu bar."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def default_last_notes_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "IdeaForge"
        / "last_notes.json"
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
