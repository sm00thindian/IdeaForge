"""Serialize GPU-heavy pipeline stages (transcribe, diarize) across sessions."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

_gpu_lock = threading.Lock()


@contextmanager
def gpu_stage() -> Iterator[None]:
    """Hold while running mlx-whisper or pyannote on Apple Silicon."""
    _gpu_lock.acquire()
    try:
        yield
    finally:
        _gpu_lock.release()