"""Audio loading, ffmpeg normalization, and WAV utilities."""

from __future__ import annotations

import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np

TARGET_SAMPLE_RATE = 16_000
_PCM_EXTENSIONS = {".wav"}
_LOSSY_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".opus"}


def is_pcm_wav(path: Path) -> bool:
    """True when path is readable PCM WAV."""
    if path.suffix.lower() != ".wav":
        return False
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getcomptype() == "NONE"
    except (OSError, wave.Error):
        return False


def needs_audio_normalization(path: Path) -> bool:
    """True when the pipeline should convert to PCM WAV before ML stages."""
    return path.suffix.lower() in _LOSSY_EXTENSIONS


def _run_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=True,
        capture_output=True,
        text=True,
    )


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_duration_seconds(path: Path) -> float:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found on PATH")
    result = _run_command([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    return float(result.stdout.strip())


def get_audio_duration_seconds(path: Path) -> float:
    """Return duration in seconds (WAV via wave, other formats via ffprobe)."""
    if path.suffix.lower() in _PCM_EXTENSIONS:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    try:
        return ffprobe_duration_seconds(path)
    except (RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as exc:
        raise wave.Error(str(exc)) from exc


def normalize_to_wav(
    path: Path,
    output_dir: Path,
    *,
    sample_rate: int = TARGET_SAMPLE_RATE,
) -> Path:
    """Convert any ffmpeg-readable audio to mono PCM WAV."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH — required for non-WAV ingest")

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{path.stem}_normalized.wav"
    if output.exists() and output.stat().st_mtime >= path.stat().st_mtime:
        return output

    _run_command([
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(output),
    ])
    return output


def ensure_pipeline_audio(
    path: Path,
    work_dir: Path,
    *,
    normalize_audio: bool,
) -> Path:
    """Return a PCM WAV path suitable for merge/transcribe/diarize."""
    if not normalize_audio or not needs_audio_normalization(path):
        return path
    return normalize_to_wav(path, work_dir)


def split_audio_fixed_window(
    path: Path,
    output_dir: Path,
    *,
    window_seconds: float,
) -> List[Path]:
    """Split audio into fixed-length WAV segments via ffmpeg."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH — required for fixed-window splitting")

    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / f"{path.stem}_part%03d.wav"
    _run_command([
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-f",
        "segment",
        "-segment_time",
        str(window_seconds),
        "-ac",
        "1",
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(pattern),
    ])
    parts = sorted(output_dir.glob(f"{path.stem}_part*.wav"))
    return parts if parts else [path]


def _parse_silence_boundaries(stderr: str) -> List[float]:
    starts: List[float] = []
    for line in stderr.splitlines():
        match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if match:
            starts.append(float(match.group(1)))
    return starts


def split_audio_by_silence(
    path: Path,
    output_dir: Path,
    *,
    min_silence_seconds: float,
) -> List[Path]:
    """Split audio at silence gaps using ffmpeg silencedetect."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH — required for silence splitting")

    detect = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise=-35dB:d={min_silence_seconds}",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    boundaries = _parse_silence_boundaries(detect.stderr)
    if not boundaries:
        return [path]

    try:
        total_duration = get_audio_duration_seconds(path)
    except (OSError, wave.Error, ValueError, RuntimeError):
        return [path]

    cut_points = [0.0] + boundaries + [total_duration]
    output_dir.mkdir(parents=True, exist_ok=True)
    parts: List[Path] = []
    for index in range(len(cut_points) - 1):
        start = cut_points[index]
        end = cut_points[index + 1]
        duration = end - start
        if duration < min_silence_seconds:
            continue
        part_path = output_dir / f"{path.stem}_part{index + 1:03d}.wav"
        _run_command([
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(path),
            "-t",
            str(duration),
            "-ac",
            "1",
            "-ar",
            str(TARGET_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(part_path),
        ])
        parts.append(part_path)

    return parts if parts else [path]


def load_audio_mono_16k(path: Path) -> Tuple[np.ndarray, float]:
    """
    Load audio as float32 mono @ 16 kHz without ffmpeg.
    Supports PCM WAV files (including Z28/Z29 recorder output).
    """
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sample_width} bytes")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    duration = len(audio) / sample_rate

    if sample_rate != TARGET_SAMPLE_RATE:
        audio = _resample(audio, sample_rate, TARGET_SAMPLE_RATE)
        duration = len(audio) / TARGET_SAMPLE_RATE

    return audio, duration


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    try:
        from scipy.signal import resample_poly  # type: ignore

        g = _gcd(src_rate, dst_rate)
        return resample_poly(audio, dst_rate // g, src_rate // g).astype(np.float32)
    except ImportError:
        duration = len(audio) / src_rate
        dst_length = int(duration * dst_rate)
        indices = np.linspace(0, len(audio) - 1, dst_length).astype(int)
        return audio[indices].astype(np.float32)


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def _wav_format_key(path: Path) -> tuple[int, int, int, str, str]:
    """Format identity for concat — excludes nframes (length differs per chunk)."""
    with wave.open(str(path), "rb") as wf:
        return (
            wf.getnchannels(),
            wf.getsampwidth(),
            wf.getframerate(),
            wf.getcomptype(),
            wf.getcompname(),
        )


def concat_wav_files(paths: Sequence[Path], output: Path) -> Path:
    """Concatenate PCM WAV files with identical format. Returns output path."""
    if not paths:
        raise ValueError("concat_wav_files requires at least one input")
    if len(paths) == 1:
        return paths[0]

    ref_format = _wav_format_key(paths[0])

    frames: list[bytes] = []
    for path in paths:
        if _wav_format_key(path) != ref_format:
            raise ValueError(
                f"WAV format mismatch: {paths[0].name} vs {path.name}"
            )
        with wave.open(str(path), "rb") as wf:
            frames.append(wf.readframes(wf.getnframes()))

    nchannels, sampwidth, framerate, comptype, compname = ref_format
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as out:
        out.setnchannels(nchannels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)
        out.setcomptype(comptype, compname)
        for chunk in frames:
            out.writeframes(chunk)
    return output