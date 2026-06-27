"""Export meeting action items to Apple Reminders and Obsidian."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ideaforge.schema import ActionItem, MeetingNotes


@dataclass
class ExportSettings:
    reminders: bool = False
    reminders_list: str = "IdeaForge"
    obsidian: bool = False
    obsidian_vault: Optional[Path] = None
    obsidian_note: str = "IdeaForge/Action Items.md"
    force: bool = False


def action_item_fingerprint(
    item: ActionItem,
    *,
    meeting_title: str,
    recording_stem: str,
) -> str:
    payload = "|".join([
        meeting_title,
        recording_stem,
        item.who,
        item.what,
        item.when or "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_export_log(archive: Path) -> Dict[str, Any]:
    path = archive / ".action_export_log.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"fingerprints": []}


def save_export_log(archive: Path, log: Dict[str, Any]) -> None:
    path = archive / ".action_export_log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def meeting_notes_from_json(path: Path) -> MeetingNotes:
    data = json.loads(path.read_text(encoding="utf-8"))
    actions = [
        ActionItem(
            who=a.get("who", "Unknown"),
            what=a.get("what", ""),
            when=a.get("when"),
            priority=a.get("priority"),
            confidence=a.get("confidence"),
            source_quote=a.get("source_quote"),
            blocked_by=a.get("blocked_by"),
        )
        for a in data.get("action_items", [])
    ]
    return MeetingNotes(
        title=data.get("title", path.stem),
        date=data.get("date", ""),
        executive_summary=data.get("executive_summary", ""),
        meeting_type=data.get("meeting_type"),
        action_items=actions,
        metadata=data.get("metadata", {}),
    )


def export_action_items(
    notes: MeetingNotes,
    *,
    archive: Path,
    recording_stem: str,
    settings: ExportSettings,
) -> int:
    """Export action items to configured destinations. Returns items exported."""
    if not notes.action_items:
        return 0
    if not settings.reminders and not settings.obsidian:
        return 0

    export_log = load_export_log(archive)
    known = set(export_log.get("fingerprints", []))
    to_export: List[ActionItem] = []

    for item in notes.action_items:
        fp = action_item_fingerprint(
            item,
            meeting_title=notes.title,
            recording_stem=recording_stem,
        )
        if settings.force or fp not in known:
            to_export.append(item)
            known.add(fp)

    if not to_export:
        print("    ↳ Action items already exported — skipping")
        return 0

    exported = 0
    if settings.reminders:
        count = _export_to_reminders(
            to_export,
            notes=notes,
            recording_stem=recording_stem,
            list_name=settings.reminders_list,
        )
        exported = max(exported, count)

    if settings.obsidian:
        count = _export_to_obsidian(
            to_export,
            notes=notes,
            recording_stem=recording_stem,
            settings=settings,
        )
        exported = max(exported, count)

    export_log["fingerprints"] = sorted(known)
    save_export_log(archive, export_log)
    return exported


def _export_to_reminders(
    items: List[ActionItem],
    *,
    notes: MeetingNotes,
    recording_stem: str,
    list_name: str,
) -> int:
    if platform.system() != "Darwin":
        print("    ⚠️  Apple Reminders export requires macOS — skipping")
        return 0

    created = 0
    for item in items:
        title = f"{item.who}: {item.what}"
        body_parts = [f"Meeting: {notes.title}"]
        if notes.date:
            body_parts.append(f"Date: {notes.date}")
        if item.when:
            body_parts.append(f"When: {item.when}")
        if item.priority:
            body_parts.append(f"Priority: {item.priority}")
        if item.confidence:
            body_parts.append(f"Confidence: {item.confidence}")
        if item.blocked_by:
            body_parts.append(f"Blocked by: {item.blocked_by}")
        if item.source_quote:
            body_parts.append(f'Source: "{item.source_quote}"')
        body_parts.append(f"Recording: {recording_stem}")
        body = "\n".join(body_parts)

        script = f'''
        tell application "Reminders"
            set targetList to missing value
            repeat with L in lists
                if name of L is "{_escape_applescript(list_name)}" then
                    set targetList to L
                    exit repeat
                end if
            end repeat
            if targetList is missing value then
                set targetList to make new list with properties {{name:"{_escape_applescript(list_name)}"}}
            end if
            tell targetList
                make new reminder with properties {{name:"{_escape_applescript(title)}", body:"{_escape_applescript(body)}"}}
            end tell
        end tell
        '''
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
            created += 1
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            err = getattr(exc, "stderr", "") or str(exc)
            print(f"    ⚠️  Reminders export failed for '{title}': {err.strip()}")
            break

    if created:
        print(f"    ✓ Exported {created} action item(s) to Reminders ({list_name})")
    return created


def _export_to_obsidian(
    items: List[ActionItem],
    *,
    notes: MeetingNotes,
    recording_stem: str,
    settings: ExportSettings,
) -> int:
    if not settings.obsidian_vault:
        print("    ⚠️  obsidian_vault not configured — skipping Obsidian export")
        return 0

    vault = settings.obsidian_vault.expanduser().resolve()
    if not vault.is_dir():
        print(f"    ⚠️  Obsidian vault not found: {vault}")
        return 0

    note_path = vault / settings.obsidian_note
    note_path.parent.mkdir(parents=True, exist_ok=True)

    section = format_obsidian_section(
        items,
        notes=notes,
        recording_stem=recording_stem,
    )

    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        if section.strip() in existing:
            print(f"    ↳ Obsidian section already present in {note_path.name}")
            return 0
        content = existing.rstrip() + "\n\n" + section
    else:
        content = (
            "---\ntags: [ideaforge, action-items]\n---\n\n"
            "# IdeaForge Action Items\n\n"
            + section
        )

    note_path.write_text(content, encoding="utf-8")
    print(f"    ✓ Exported {len(items)} action item(s) to Obsidian: {note_path}")
    return len(items)


def format_obsidian_section(
    items: List[ActionItem],
    *,
    notes: MeetingNotes,
    recording_stem: str,
) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    heading_date = notes.date or datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"## {notes.title} — {heading_date}",
        "",
        f"*Exported {stamp} from [[{recording_stem}_summary]]*",
        "",
    ]
    for item in items:
        when = f" — {item.when}" if item.when else ""
        lines.append(f"- [ ] **{item.who}:** {item.what}{when} `#ideaforge`")
        if item.priority:
            lines.append(f"  - priority:: {item.priority}")
        if item.confidence:
            lines.append(f"  - confidence:: {item.confidence}")
        if item.blocked_by:
            lines.append(f"  - blocked_by:: {item.blocked_by}")
        if item.source_quote:
            lines.append(f'  - source:: "{item.source_quote}"')
        lines.append(f"  - recording:: [[{recording_stem}]]")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def export_summaries_in_folder(
    folder: Path,
    archive: Path,
    settings: ExportSettings,
) -> int:
    """Export action items from all *_summary.json files in folder."""
    total = 0
    for summary_path in sorted(folder.glob("*_summary.json")):
        notes = meeting_notes_from_json(summary_path)
        if not notes.action_items:
            continue
        recording_stem = summary_path.stem.removesuffix("_summary")
        print(f"\n📤 Exporting from {summary_path.name}")
        total += export_action_items(
            notes,
            archive=archive,
            recording_stem=recording_stem,
            settings=settings,
        )
    return total