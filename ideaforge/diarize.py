"""Speaker diarization via pyannote — no re-transcription."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ideaforge.audio_util import TARGET_SAMPLE_RATE, load_audio_mono_16k
from ideaforge.status import active_reporter, status_touch
from ideaforge.transcription_types import SpeakerTurn, TranscriptSegment

PIPELINE_MODELS = (
    "pyannote/speaker-diarization-community-1",
    "pyannote/speaker-diarization-3.1",
)

GATED_MODEL_URLS = (
    "https://huggingface.co/pyannote/speaker-diarization-community-1",
    "https://huggingface.co/pyannote/speaker-diarization-3.1",
    "https://huggingface.co/pyannote/segmentation-3.0",
)


def save_turns_cache(path: Path, turns: List[SpeakerTurn], audio_file: str) -> None:
    payload = {
        "audio_file": audio_file,
        "cached_at": datetime.now().isoformat(timespec="seconds"),
        "turn_count": len(turns),
        "turns": [
            {"start": t.start, "end": t.end, "speaker": t.speaker}
            for t in turns
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_cached_turns(path: Path) -> Optional[List[SpeakerTurn]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        turns = data.get("turns", [])
        return [
            SpeakerTurn(
                start=float(t["start"]),
                end=float(t["end"]),
                speaker=str(t["speaker"]),
            )
            for t in turns
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def _load_pipeline(hf_token: str) -> Any:
    from pyannote.audio import Pipeline  # type: ignore

    last_error: Optional[Exception] = None
    for model_id in PIPELINE_MODELS:
        try:
            try:
                return Pipeline.from_pretrained(model_id, token=hf_token)
            except TypeError:
                return Pipeline.from_pretrained(model_id, use_auth_token=hf_token)
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("No diarization pipeline available")


def _extract_turns(diarization: Any) -> List[SpeakerTurn]:
    turns: List[SpeakerTurn] = []

    speaker_diarization = getattr(diarization, "speaker_diarization", None)
    if speaker_diarization is not None:
        for turn, speaker in speaker_diarization:
            turns.append(
                SpeakerTurn(
                    start=float(turn.start),
                    end=float(turn.end),
                    speaker=str(speaker),
                )
            )
        return turns

    if hasattr(diarization, "itertracks"):
        for segment, _, speaker in diarization.itertracks(yield_label=True):
            turns.append(
                SpeakerTurn(
                    start=float(segment.start),
                    end=float(segment.end),
                    speaker=str(speaker),
                )
            )
    return turns


def _diarization_kwargs(
    min_speakers: Optional[int],
    max_speakers: Optional[int],
) -> Dict[str, int]:
    kwargs: Dict[str, int] = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers
    return kwargs


def diarize_audio(
    audio_path: Path,
    hf_token: str,
    *,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> Optional[List[SpeakerTurn]]:
    """Run pyannote speaker diarization. Returns speaker turns or None on failure."""
    try:
        import torch  # type: ignore
    except ImportError:
        print("    ⚠️  torch not installed (pip install torch)")
        return None

    try:
        import warnings

        warnings.filterwarnings(
            "ignore",
            message="torchcodec is not installed correctly",
            category=UserWarning,
        )
        from pyannote.audio import Pipeline  # type: ignore  # noqa: F401
    except ImportError:
        print("    ⚠️  pyannote.audio not installed (pip install 'ideaforge[diarize]')")
        return None

    try:
        hint = ""
        if min_speakers or max_speakers:
            hint = f" (min={min_speakers or '—'}, max={max_speakers or '—'})"
        print(f"    🗣️  Running pyannote speaker diarization{hint} ...")
        status_touch(
            stage="Diarizing",
            clear_progress=True,
            detail=f"Analyzing {audio_path.name}",
        )
        reporter = active_reporter()
        if reporter is not None:
            reporter.set_step_active("diarize", detail=audio_path.name)
        pipeline = _load_pipeline(hf_token)

        audio_np, _ = load_audio_mono_16k(audio_path)
        waveform = torch.from_numpy(audio_np).unsqueeze(0)
        diar_kwargs = _diarization_kwargs(min_speakers, max_speakers)

        diarization = pipeline(
            {"waveform": waveform, "sample_rate": TARGET_SAMPLE_RATE},
            **diar_kwargs,
        )

        turns = _extract_turns(diarization)
        print(f"    ✓ Diarization complete ({len(turns)} speaker turns)")
        return turns
    except Exception as exc:
        msg = str(exc)
        if "403" in msg or "gated" in msg.lower() or "authorized list" in msg.lower():
            print("    ⚠️  Diarization failed: Hugging Face gated model access not granted")
            print("       Accept ALL licenses on your Hugging Face account:")
            for url in GATED_MODEL_URLS:
                print(f"       • {url}")
        else:
            print(f"    ⚠️  Diarization failed: {exc}")
        return None


def assign_speakers(
    segments: List[TranscriptSegment],
    turns: List[SpeakerTurn],
) -> List[TranscriptSegment]:
    """Assign speaker labels to transcript segments by temporal overlap."""
    if not turns:
        return segments

    labeled: List[TranscriptSegment] = []
    for seg in segments:
        speaker = _best_speaker_for_segment(seg.start, seg.end, turns)
        labeled.append(
            TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=speaker,
            )
        )
    return labeled


def _best_speaker_for_segment(
    start: float,
    end: float,
    turns: List[SpeakerTurn],
) -> str:
    best_speaker = "SPEAKER_UNKNOWN"
    best_overlap = 0.0
    seg_duration = max(end - start, 0.001)

    for turn in turns:
        overlap = _overlap(start, end, turn.start, turn.end)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker

    if best_overlap / seg_duration < 0.10:
        return "SPEAKER_UNKNOWN"
    return best_speaker


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))