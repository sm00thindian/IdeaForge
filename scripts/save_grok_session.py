#!/usr/bin/env python3
"""Write .last-grok-session.json so the next session can resume IdeaForge work."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote


def _repo_root() -> Path:
    return Path(
        os.environ.get("GROK_WORKSPACE_ROOT")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or Path(__file__).resolve().parent.parent
    )


def _grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME", Path.home() / ".grok"))


def _encode_cwd(cwd: Path) -> str:
    return quote(str(cwd.resolve()), safe="")


def _session_id_from_stdin() -> Optional[str]:
    if sys.stdin.isatty():
        return None
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return None
    session_id = payload.get("sessionId") or payload.get("session_id")
    return str(session_id) if session_id else None


def _resolve_session_id(cwd: Path) -> Optional[str]:
    session_id = os.environ.get("GROK_SESSION_ID") or _session_id_from_stdin()
    if session_id:
        return session_id

    sessions_root = _grok_home() / "sessions" / _encode_cwd(cwd)
    if not sessions_root.is_dir():
        return None

    summaries: List[tuple[float, str]] = []
    for child in sessions_root.iterdir():
        summary_path = child / "summary.json"
        if not summary_path.is_file():
            continue
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            updated = data.get("updated_at") or data.get("last_active_at") or ""
            summaries.append((updated, child.name))
        except (json.JSONDecodeError, OSError):
            continue

    if not summaries:
        return None
    summaries.sort(reverse=True)
    return summaries[0][1]


def _session_dir(cwd: Path, session_id: str) -> Path:
    return _grok_home() / "sessions" / _encode_cwd(cwd) / session_id


def _load_summary(session_dir: Path) -> Dict[str, Any]:
    summary_path = session_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _recent_topics(session_dir: Path, *, limit: int = 5) -> List[str]:
    updates_path = session_dir / "updates.jsonl"
    if not updates_path.is_file():
        return []

    topics: List[str] = []
    try:
        lines = updates_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for line in reversed(lines[-400:]):
        if len(topics) >= limit:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = _extract_user_text(event)
        if text and _is_substantive_user_topic(text):
            topics.append(text.strip().replace("\n", " ")[:240])
    topics.reverse()
    return topics


def _extract_user_text(event: Dict[str, Any]) -> Optional[str]:
    params = event.get("params")
    if isinstance(params, dict):
        update = params.get("update")
        if isinstance(update, dict):
            session_update = update.get("sessionUpdate")
            content = update.get("content")
            if session_update in {"user_message", "user_message_chunk"} and isinstance(
                content, dict
            ):
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text

    for key in ("userMessage", "prompt", "text", "content"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                return joined
    return None


def _is_substantive_user_topic(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 12:
        return False
    lowered = cleaned.lower()
    if lowered.startswith("system/context prompt"):
        return False
    if lowered.startswith("<user_query>") and len(cleaned) < 80:
        return False
    return True


def _git_field(args: List[str], cwd: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    value = result.stdout.strip()
    return value or None


def _load_existing_notes(output_path: Path) -> Dict[str, Any]:
    if not output_path.is_file():
        return {}
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        "next_steps": data.get("next_steps", []),
        "notes": data.get("notes", ""),
    }


def build_session_snapshot(
    *,
    cwd: Optional[Path] = None,
    session_id: Optional[str] = None,
    next_steps: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    root = (cwd or _repo_root()).resolve()
    session_id = session_id or _resolve_session_id(root)
    if not session_id:
        raise RuntimeError("Could not resolve Grok session id")

    session_dir = _session_dir(root, session_id)
    summary = _load_summary(session_dir)
    info = summary.get("info", {})
    output_path = root / ".last-grok-session.json"
    preserved = _load_existing_notes(output_path)

    transcript_path = session_dir / "updates.jsonl"
    title = (
        summary.get("generated_title")
        or summary.get("session_summary")
        or "IdeaForge session"
    )

    snapshot: Dict[str, Any] = {
        "session_id": session_id,
        "title": title,
        "summary": summary.get("session_summary", ""),
        "cwd": str(info.get("cwd") or root),
        "git_branch": _git_field(["rev-parse", "--abbrev-ref", "HEAD"], root),
        "git_commit": _git_field(["rev-parse", "HEAD"], root),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "model": summary.get("current_model_id"),
        "resume": {
            "grok_cli": f"grok --resume {session_id}",
            "grok_continue": "grok -c",
            "cursor_hint": (
                "Read .last-grok-session.json and the transcript at session_path "
                "before continuing IdeaForge work."
            ),
        },
        "session_path": str(transcript_path) if transcript_path.is_file() else str(session_dir),
        "recent_topics": _recent_topics(session_dir),
        "next_steps": next_steps if next_steps is not None else preserved.get("next_steps", []),
        "notes": notes if notes is not None else preserved.get("notes", ""),
    }
    return snapshot


def save_session(
    *,
    cwd: Optional[Path] = None,
    session_id: Optional[str] = None,
    next_steps: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Path:
    root = (cwd or _repo_root()).resolve()
    snapshot = build_session_snapshot(
        cwd=root,
        session_id=session_id,
        next_steps=next_steps,
        notes=notes,
    )
    output_path = root / ".last-grok-session.json"
    output_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--note", default=None, help="Freeform note for the next session")
    parser.add_argument(
        "--next-step",
        action="append",
        default=[],
        dest="next_steps",
        help="Action item for the next session (repeatable)",
    )
    args = parser.parse_args()

    try:
        output = save_session(
            session_id=args.session_id,
            next_steps=args.next_steps or None,
            notes=args.note,
        )
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Saved session snapshot → {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())