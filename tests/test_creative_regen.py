"""Tests for creative regenerate helpers."""

from pathlib import Path
from unittest.mock import patch

from ideaforge.config import IdeaForgeConfig
from ideaforge.creative_regen import (
    find_session_artifacts,
    list_sidecars_for_note_path,
    prior_creative_seed,
    regenerate_creative,
)


def test_find_session_artifacts_nested(tmp_path: Path):
    stem = "R2026-06-30-10-00-00"
    session = tmp_path / "2026-06-30" / stem
    session.mkdir(parents=True)
    (session / f"{stem}.txt").write_text("song idea about rain " * 20, encoding="utf-8")
    paths = find_session_artifacts(tmp_path, stem)
    assert paths is not None
    assert paths["transcript"].is_file()


def test_prior_creative_seed(tmp_path: Path):
    js = tmp_path / "R1_summary.json"
    js.write_text(
        '{"title": "Rain", "intent": "song_idea", "chorus_hook": "drip"}',
        encoding="utf-8",
    )
    seed = prior_creative_seed(js)
    assert seed is not None
    assert seed["title"] == "Rain"


def test_list_sidecars_for_note_path(tmp_path: Path):
    stem = "R2026-06-30-10-00-00"
    session = tmp_path / "2026-06-30" / stem
    session.mkdir(parents=True)
    suno = session / f"{stem}_suno.txt"
    suno.write_text("style", encoding="utf-8")
    md = tmp_path / "2026-06-30" / "20260630 - Rain.md"
    md.write_text("# rain", encoding="utf-8")
    found = list_sidecars_for_note_path(str(md), stem=stem)
    labels = {label for label, _ in found}
    assert "Suno" in labels


def test_regenerate_creative_calls_process_transcript(tmp_path: Path):
    stem = "R2026-06-30-10-00-00"
    session = tmp_path / "2026-06-30" / stem
    session.mkdir(parents=True)
    (session / f"{stem}.txt").write_text(
        "song idea about summer nights on the porch with fireflies. " * 5,
        encoding="utf-8",
    )
    md = session / f"{stem}_summary.md"
    cfg = IdeaForgeConfig(archive=tmp_path)

    def fake_process(transcript_path, output_dir, **kwargs):
        assert kwargs.get("force") is True
        assert kwargs.get("mode") == "creative"
        md.write_text("# regen", encoding="utf-8")
        return md

    with patch("ideaforge.creative_regen.process_transcript", side_effect=fake_process):
        code, path, message = regenerate_creative(tmp_path, stem, cfg)
    assert code == 0
    assert path is not None
    assert "Regenerated" in message
