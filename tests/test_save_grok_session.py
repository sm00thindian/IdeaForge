"""Tests for local Grok session snapshot helper."""

import json
from pathlib import Path

from scripts.save_grok_session import build_session_snapshot, save_session


def test_save_session_writes_gitignored_file(tmp_path: Path, monkeypatch):
    repo = tmp_path / "IdeaForge"
    repo.mkdir()
    monkeypatch.setenv("GROK_WORKSPACE_ROOT", str(repo))

    output = save_session(
        cwd=repo,
        session_id="test-session-id",
        next_steps=["Ship feature X"],
        notes="Paused mid-refactor",
    )

    assert output == repo / ".last-grok-session.json"
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["session_id"] == "test-session-id"
    assert data["next_steps"] == ["Ship feature X"]
    assert data["notes"] == "Paused mid-refactor"
    assert "grok --resume test-session-id" in data["resume"]["grok_cli"]


def test_save_session_preserves_notes_when_not_provided(tmp_path: Path, monkeypatch):
    repo = tmp_path / "IdeaForge"
    repo.mkdir()
    existing = repo / ".last-grok-session.json"
    existing.write_text(
        json.dumps({"next_steps": ["Keep going"], "notes": "Old note"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROK_WORKSPACE_ROOT", str(repo))

    save_session(cwd=repo, session_id="abc")

    data = json.loads(existing.read_text(encoding="utf-8"))
    assert data["notes"] == "Old note"
    assert data["next_steps"] == ["Keep going"]


def test_build_session_snapshot_uses_env_session_id(tmp_path: Path, monkeypatch):
    repo = tmp_path / "IdeaForge"
    repo.mkdir()
    monkeypatch.setenv("GROK_WORKSPACE_ROOT", str(repo))
    monkeypatch.setenv("GROK_SESSION_ID", "from-env")

    snapshot = build_session_snapshot(cwd=repo)
    assert snapshot["session_id"] == "from-env"