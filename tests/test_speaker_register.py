"""Tests for speakers register command."""

import json
from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.speaker_library import find_session_folder, register_speaker_from_session


def _write_session(folder: Path, stem: str) -> None:
    turns = {
        "turns": [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]
    }
    (folder / f"{stem}_turns.json").write_text(json.dumps(turns), encoding="utf-8")
    (folder / f"{stem}.wav").write_bytes(b"\x00" * 100)


def test_find_session_folder(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    folder = archive / "2026-06-30"
    folder.mkdir(parents=True)
    stem = "R2026-06-30-10-00-00"
    _write_session(folder, stem)
    cfg = IdeaForgeConfig(archive=archive)
    assert find_session_folder(cfg, stem) == folder


def test_register_speaker_from_session(tmp_path: Path):
    archive = tmp_path / "IdeaForge"
    folder = archive / "2026-06-30"
    folder.mkdir(parents=True)
    stem = "R2026-06-30-10-00-00"
    _write_session(folder, stem)
    library_path = tmp_path / "library.json"
    cfg = IdeaForgeConfig(archive=archive, hf_token="hf_test", speaker_library_path=library_path)

    with patch(
        "ideaforge.speaker_library.extract_speaker_embeddings",
        return_value={"SPEAKER_00": [1.0, 0.0, 0.0]},
    ):
        entry = register_speaker_from_session(
            cfg,
            session_stem=stem,
            speaker_label="SPEAKER_00",
            name="Alex",
        )

    assert entry.name == "Alex"
    assert library_path.is_file()