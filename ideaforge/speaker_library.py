"""Persistent speaker embeddings for cross-session label reuse."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ideaforge.transcription_types import SpeakerTurn

SPEAKER_LIBRARY_SCHEMA_VERSION = 1
DEFAULT_LIBRARY_PATH = (
    Path.home() / "Library" / "Application Support" / "IdeaForge" / "speaker_library.json"
)


@dataclass
class SpeakerEntry:
    speaker_id: str
    name: str
    embedding: List[float]
    sessions: List[str]
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "name": self.name,
            "embedding": self.embedding,
            "sessions": self.sessions,
            "updated_at": self.updated_at,
        }


def default_library_path() -> Path:
    return DEFAULT_LIBRARY_PATH


def empty_library() -> Dict[str, Any]:
    return {"schema_version": SPEAKER_LIBRARY_SCHEMA_VERSION, "speakers": {}}


def load_speaker_library(path: Optional[Path] = None) -> Dict[str, Any]:
    library_path = (path or default_library_path()).expanduser()
    if not library_path.is_file():
        return empty_library()
    try:
        data = json.loads(library_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty_library()
    if "speakers" not in data:
        data["speakers"] = {}
    data["schema_version"] = int(data.get("schema_version", 1))
    return data


def save_speaker_library(library: Dict[str, Any], path: Optional[Path] = None) -> None:
    library_path = (path or default_library_path()).expanduser()
    library_path.parent.mkdir(parents=True, exist_ok=True)
    library["schema_version"] = SPEAKER_LIBRARY_SCHEMA_VERSION
    library_path.write_text(json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8")


def cosine_similarity(left: List[float], right: List[float]) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    if a.size != b.size:
        size = min(a.size, b.size)
        a = a[:size]
        b = b[:size]
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def match_speaker(
    embedding: List[float],
    library: Dict[str, Any],
    *,
    threshold: float,
) -> Optional[Tuple[str, str, float]]:
    """Return (speaker_id, name, score) for the best library match above threshold."""
    best: Optional[Tuple[str, str, float]] = None
    for speaker_id, entry in library.get("speakers", {}).items():
        score = cosine_similarity(embedding, entry.get("embedding", []))
        if score < threshold:
            continue
        if best is None or score > best[2]:
            best = (speaker_id, str(entry.get("name", speaker_id)), score)
    return best


def register_speaker(
    library: Dict[str, Any],
    *,
    name: str,
    embedding: List[float],
    session_stem: str,
) -> SpeakerEntry:
    speaker_id = str(uuid.uuid4())
    entry = SpeakerEntry(
        speaker_id=speaker_id,
        name=name,
        embedding=embedding,
        sessions=[session_stem],
        updated_at=datetime.now().isoformat(timespec="seconds"),
    )
    library.setdefault("speakers", {})[speaker_id] = entry.to_dict()
    return entry


def update_speaker_session(
    library: Dict[str, Any],
    *,
    speaker_id: str,
    session_stem: str,
) -> None:
    entry = library.get("speakers", {}).get(speaker_id)
    if not entry:
        return
    sessions = list(entry.get("sessions", []))
    if session_stem not in sessions:
        sessions.append(session_stem)
    entry["sessions"] = sessions
    entry["updated_at"] = datetime.now().isoformat(timespec="seconds")


def list_speakers(library: Dict[str, Any]) -> List[SpeakerEntry]:
    speakers: List[SpeakerEntry] = []
    for speaker_id, raw in library.get("speakers", {}).items():
        speakers.append(
            SpeakerEntry(
                speaker_id=speaker_id,
                name=str(raw.get("name", speaker_id)),
                embedding=list(raw.get("embedding", [])),
                sessions=list(raw.get("sessions", [])),
                updated_at=str(raw.get("updated_at", "")),
            )
        )
    return sorted(speakers, key=lambda item: item.name.lower())


def _longest_turn_per_speaker(turns: List[SpeakerTurn]) -> Dict[str, SpeakerTurn]:
    best: Dict[str, SpeakerTurn] = {}
    for turn in turns:
        current = best.get(turn.speaker)
        duration = turn.end - turn.start
        if current is None or (current.end - current.start) < duration:
            best[turn.speaker] = turn
    return best


def extract_speaker_embeddings(
    audio_path: Path,
    turns: List[SpeakerTurn],
    hf_token: str,
) -> Dict[str, List[float]]:
    """
    Extract one embedding per diarization label using pyannote/embedding.

    Returns an empty dict when pyannote/torch are unavailable.
    """
    if not turns:
        return {}

    try:
        import torch  # type: ignore
        from pyannote.audio import Inference  # type: ignore
    except ImportError:
        return {}

    try:
        inference = Inference("pyannote/embedding", token=hf_token)
    except TypeError:
        try:
            inference = Inference("pyannote/embedding", use_auth_token=hf_token)
        except Exception:
            return {}
    except Exception:
        return {}

    from ideaforge.audio_util import TARGET_SAMPLE_RATE, load_audio_mono_16k

    audio_np, _ = load_audio_mono_16k(audio_path)
    waveform = torch.from_numpy(audio_np).unsqueeze(0)
    embeddings: Dict[str, List[float]] = {}

    for speaker, turn in _longest_turn_per_speaker(turns).items():
        start = max(int(turn.start * TARGET_SAMPLE_RATE), 0)
        end = min(int(turn.end * TARGET_SAMPLE_RATE), audio_np.shape[0])
        if end <= start:
            continue
        crop = waveform[:, start:end]
        try:
            vector = inference({"waveform": crop, "sample_rate": TARGET_SAMPLE_RATE})
        except Exception:
            continue
        if hasattr(vector, "detach"):
            vector = vector.detach().cpu().numpy()
        embeddings[speaker] = np.asarray(vector, dtype=np.float32).reshape(-1).tolist()

    return embeddings


def build_library_speaker_map(
    embeddings: Dict[str, List[float]],
    library: Dict[str, Any],
    *,
    threshold: float,
) -> Dict[str, str]:
    """Map pyannote labels (SPEAKER_00) to known library names."""
    mapping: Dict[str, str] = {}
    for label, embedding in embeddings.items():
        match = match_speaker(embedding, library, threshold=threshold)
        if match is not None:
            _speaker_id, name, _score = match
            mapping[label] = name
    return mapping


def learn_speakers_from_session(
    library: Dict[str, Any],
    *,
    embeddings: Dict[str, List[float]],
    applied_map: Dict[str, str],
    session_stem: str,
    threshold: float,
) -> None:
    """
    Register unseen speakers and refresh session lists for known matches.

    Uses applied_map values (manual or library names) as display names for new entries.
    """
    for label, embedding in embeddings.items():
        match = match_speaker(embedding, library, threshold=threshold)
        if match is not None:
            update_speaker_session(library, speaker_id=match[0], session_stem=session_stem)
            continue

        display_name = applied_map.get(label, label)
        if display_name.startswith("SPEAKER_"):
            continue
        register_speaker(
            library,
            name=display_name,
            embedding=embedding,
            session_stem=session_stem,
        )


def apply_speaker_library(
    audio_path: Path,
    turns: List[SpeakerTurn],
    *,
    hf_token: str,
    speaker_map: Optional[Dict[str, str]],
    session_stem: str,
    enabled: bool,
    auto_apply: bool,
    auto_learn: bool,
    threshold: float,
    library_path: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Match diarization labels against the library and optionally learn new speakers.

    Returns the combined speaker map to apply to transcript segments.
    """
    base_map = dict(speaker_map or {})
    if not enabled or not auto_apply:
        return base_map

    embeddings = extract_speaker_embeddings(audio_path, turns, hf_token)
    if not embeddings:
        return base_map

    library = load_speaker_library(library_path)
    library_map = build_library_speaker_map(embeddings, library, threshold=threshold)
    combined = {**library_map, **base_map}

    if auto_learn:
        learn_speakers_from_session(
            library,
            embeddings=embeddings,
            applied_map=combined,
            session_stem=session_stem,
            threshold=threshold,
        )
        save_speaker_library(library, library_path)

    if library_map:
        matched = ", ".join(f"{label}→{name}" for label, name in library_map.items())
        print(f"    ✓ Speaker library matched: {matched}")

    return combined