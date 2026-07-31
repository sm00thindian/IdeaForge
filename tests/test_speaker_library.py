"""Tests for speaker embedding library."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ideaforge.speaker_library import (
    SpeakerEmbeddingError,
    build_library_speaker_map,
    cosine_similarity,
    empty_library,
    extract_speaker_embeddings,
    learn_speakers_from_session,
    load_speaker_library,
    match_speaker,
    register_speaker,
    save_speaker_library,
)
from ideaforge.transcription_types import SpeakerTurn


def test_cosine_similarity_identical_vectors():
    vector = [1.0, 0.0, 0.0]
    assert cosine_similarity(vector, vector) == 1.0


def test_match_speaker_above_threshold():
    library = empty_library()
    embedding = [1.0, 0.0, 0.0]
    register_speaker(library, name="Alex", embedding=embedding, session_stem="s1")
    match = match_speaker([0.99, 0.01, 0.0], library, threshold=0.75)
    assert match is not None
    assert match[1] == "Alex"


def test_build_library_speaker_map():
    library = empty_library()
    register_speaker(library, name="Kilynn", embedding=[1.0, 0.0], session_stem="s1")
    mapping = build_library_speaker_map(
        {"SPEAKER_00": [0.98, 0.02, 0.0]},
        library,
        threshold=0.75,
    )
    assert mapping["SPEAKER_00"] == "Kilynn"


def test_learn_speakers_registers_named_labels(tmp_path):
    library = empty_library()
    learn_speakers_from_session(
        library,
        embeddings={"SPEAKER_00": [1.0, 0.0, 0.0]},
        applied_map={"SPEAKER_00": "Jordan"},
        session_stem="R2026-06-30-10-00-00",
        threshold=0.99,
    )
    assert len(library["speakers"]) == 1
    path = tmp_path / "library.json"
    save_speaker_library(library, path)
    reloaded = load_speaker_library(path)
    assert len(reloaded["speakers"]) == 1


def test_match_speaker_rejects_low_similarity():
    library = empty_library()
    register_speaker(library, name="Alex", embedding=[1.0, 0.0, 0.0], session_stem="s1")
    match = match_speaker([0.0, 1.0, 0.0], library, threshold=0.75)
    assert match is None
    assert np.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)


def test_extract_speaker_embeddings_uses_model_from_pretrained(tmp_path: Path):
    """pyannote 4.x: load Model then Inference(window=whole), not Inference(id, token=)."""
    audio = tmp_path / "clip.wav"
    # 1s mono 16k silence as float32 raw is not a real wav — mock load instead.
    turns = [
        SpeakerTurn(start=0.0, end=1.0, speaker="SPEAKER_00"),
        SpeakerTurn(start=1.0, end=2.0, speaker="SPEAKER_01"),
    ]
    fake_audio = np.zeros(32_000, dtype=np.float32)  # 2s @ 16 kHz
    mock_inference = MagicMock(return_value=np.ones(8, dtype=np.float32))
    mock_model = MagicMock()

    with (
        patch(
            "ideaforge.speaker_library._load_embedding_inference",
            return_value=mock_inference,
        ),
        patch(
            "ideaforge.audio_util.load_audio_mono_16k",
            return_value=(fake_audio, 16_000),
        ),
    ):
        result = extract_speaker_embeddings(audio, turns, hf_token="hf_test", strict=True)

    assert set(result) == {"SPEAKER_00", "SPEAKER_01"}
    assert all(len(v) == 8 for v in result.values())
    assert mock_inference.call_count == 2


def test_extract_speaker_embeddings_strict_raises_on_model_failure(tmp_path: Path):
    turns = [SpeakerTurn(start=0.0, end=1.0, speaker="SPEAKER_00")]
    with patch(
        "ideaforge.speaker_library._load_embedding_inference",
        side_effect=SpeakerEmbeddingError("no model"),
    ):
        with pytest.raises(SpeakerEmbeddingError, match="no model"):
            extract_speaker_embeddings(
                tmp_path / "x.wav", turns, hf_token="hf_test", strict=True
            )


def test_extract_speaker_embeddings_soft_returns_empty_on_model_failure(tmp_path: Path):
    turns = [SpeakerTurn(start=0.0, end=1.0, speaker="SPEAKER_00")]
    with patch(
        "ideaforge.speaker_library._load_embedding_inference",
        side_effect=SpeakerEmbeddingError("no model"),
    ):
        result = extract_speaker_embeddings(
            tmp_path / "x.wav", turns, hf_token="hf_test", strict=False
        )
    assert result == {}