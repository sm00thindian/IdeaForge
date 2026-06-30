"""Parallel session execution pool."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore

from ideaforge.chunks import RecordingGroup
from ideaforge.notify import RecordingResult
from ideaforge.status import StatusReporter

SessionRunner = Callable[[int, RecordingGroup], tuple[int, int, RecordingResult]]
FailureHandler = Callable[[RecordingGroup, Exception], None]


def run_session_groups(
    groups: List[RecordingGroup],
    *,
    run_one: SessionRunner,
    max_workers: int,
    reporter: StatusReporter,
    on_failure: FailureHandler,
    show_progress: bool = True,
) -> List[tuple[int, int, RecordingResult]]:
    """Run session workers sequentially or in parallel."""
    recordings: List[tuple[int, int, RecordingResult]] = []
    workers = min(max_workers, len(groups))

    if workers <= 1:
        iterator = tqdm(groups, desc="Processing") if show_progress and tqdm else groups
        for session_index, group in enumerate(iterator, start=1):
            try:
                processed, skipped, brief = run_one(session_index, group)
            except Exception as exc:
                on_failure(group, exc)
                recordings.append(
                    (0, 0, RecordingResult(stem=group.session_stem, failed=True))
                )
                continue
            recordings.append((processed, skipped, brief))
        return recordings

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_one, index, group): group
            for index, group in enumerate(groups, start=1)
        }
        for future in as_completed(futures):
            group = futures[future]
            try:
                processed, skipped, brief = future.result()
            except Exception as exc:
                on_failure(group, exc)
                recordings.append(
                    (0, 0, RecordingResult(stem=group.session_stem, failed=True))
                )
                continue
            recordings.append((processed, skipped, brief))
    return recordings


def session_log_lock(max_workers: int) -> Optional[threading.Lock]:
    """Return a lock when multiple sessions may write the processed log."""
    return threading.Lock() if max_workers > 1 else None