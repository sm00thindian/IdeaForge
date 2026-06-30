"""Tests for speaker embedding library."""

import numpy as np

from ideaforge.speaker_library import (
    build_library_speaker_map,
    cosine_similarity,
    empty_library,
    learn_speakers_from_session,
    load_speaker_library,
    match_speaker,
    register_speaker,
    save_speaker_library,
)


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