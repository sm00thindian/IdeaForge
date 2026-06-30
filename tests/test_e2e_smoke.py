"""End-to-end pipeline smoke test — no GPU, mocked ML backends."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import wave

from ideaforge.config import IdeaForgeConfig
from ideaforge.pipeline import PipelineStages
from ideaforge.runner import process_source


def _write_wav(path: Path, *, duration_seconds: float = 2.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 12_000
    samples = np.zeros(int(rate * duration_seconds), dtype=np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


@pytest.mark.e2e
def test_e2e_smoke_copy_transcribe_summarize(tmp_path: Path):
    """Fixture WAV through full pipeline produces transcript and meeting notes."""
    source = tmp_path / "device" / "RECORD"
    archive = tmp_path / "IdeaForge"
    source.mkdir(parents=True)

    stamp = datetime(2026, 6, 30, 9, 0, 0).strftime("R%Y-%m-%d-%H-%M-%S.WAV")
    wav = source / stamp
    _write_wav(wav, duration_seconds=5.0)

    cfg = IdeaForgeConfig(archive=archive, min_file_size_bytes=1_000)
    stages = PipelineStages(copy=True, transcribe=True, diarize=False, llm=True)
    stem = "R2026-06-30-09-00-00"

    def fake_transcribe(audio_path, output_dir, **kwargs):
        session_stem = kwargs.get("output_stem", audio_path.stem)
        transcript = output_dir / f"{session_stem}.txt"
        transcript.write_text(
            "Alice: Let's ship the feature by Friday.\nBob: Agreed, I'll own the API work.\n"
            * 5,
            encoding="utf-8",
        )
        return transcript

    def fake_llm(transcript_path, output_dir, **kwargs):
        session_stem = transcript_path.stem
        md_path = output_dir / f"{session_stem}_summary.md"
        json_path = output_dir / f"{session_stem}_summary.json"
        md_path.write_text("# Weekly sync\n\n## Action items\n- Bob: API work\n", encoding="utf-8")
        json_path.write_text(
            '{"title": "Weekly sync", "action_items": [{"who": "Bob", "what": "API work"}]}',
            encoding="utf-8",
        )
        return md_path

    with (
        patch("ideaforge.session_worker.transcribe_audio", side_effect=fake_transcribe),
        patch("ideaforge.session_worker.process_transcript", side_effect=fake_llm),
    ):
        result = process_source(
            source,
            archive,
            cfg,
            stages,
            show_header=False,
            show_progress=False,
        )

    assert result.files_processed == 1
    transcript = next(archive.rglob(f"{stem}.txt"))
    summary_md = next(archive.rglob(f"{stem}_summary.md"))
    summary_json = next(archive.rglob(f"{stem}_summary.json"))
    archive_wav = next(archive.rglob(stamp))
    assert transcript.is_file()
    assert summary_md.is_file()
    assert "# Weekly sync" in summary_md.read_text(encoding="utf-8")
    assert summary_json.is_file()
    assert archive_wav.is_file()