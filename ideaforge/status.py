"""Pipeline status for desktop progress UI (menu bar, notifications).

Public facade — implementation lives in:

- ``status_model`` — constants, ``PipelineStatus``, load/save
- ``status_reporter`` — ``StatusReporter``, ``status_touch``
- ``status_cli_probe`` — CLI process discovery / display enrichment
- ``last_notes`` — last-run markdown links for the menubar
"""

from __future__ import annotations

from ideaforge.last_notes import (
    LastNote,
    clear_last_notes,
    default_last_notes_path,
    last_notes_from_recordings,
    load_last_notes,
    record_last_notes_from_recordings,
    save_last_notes,
    seed_last_notes_from_archive,
)
from ideaforge.status_cli_probe import (
    _parse_cli_log_progress,
    _parse_ps_elapsed,
    _pid_alive,
    _status_from_cli_pipeline,
    find_cli_pipeline_pids,
    is_status_owned_by_other,
    resolve_display_status,
)
from ideaforge.status_model import (
    STATE_COMPLETE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PROCESSING,
    STATE_SETTLING,
    STATE_WATCHING,
    STEP_ACTIVE,
    STEP_DONE,
    STEP_PENDING,
    STEP_SKIPPED,
    PipelineStatus,
    Stage,
    StatusStep,
    StepId,
    StepLabel,
    default_status_path,
    format_elapsed,
    format_eta,
    load_status,
    menu_bar_title,
    save_status,
)
from ideaforge.status_reporter import (
    StatusReporter,
    active_reporter,
    build_step_plan,
    run_with_active_reporter,
    status_touch,
)

__all__ = [
    "LastNote",
    "PipelineStatus",
    "STATE_COMPLETE",
    "STATE_ERROR",
    "STATE_IDLE",
    "STATE_PROCESSING",
    "STATE_SETTLING",
    "STATE_WATCHING",
    "STEP_ACTIVE",
    "STEP_DONE",
    "STEP_PENDING",
    "STEP_SKIPPED",
    "Stage",
    "StatusReporter",
    "StatusStep",
    "StepId",
    "StepLabel",
    "active_reporter",
    "build_step_plan",
    "clear_last_notes",
    "default_last_notes_path",
    "default_status_path",
    "find_cli_pipeline_pids",
    "format_elapsed",
    "format_eta",
    "is_status_owned_by_other",
    "last_notes_from_recordings",
    "load_last_notes",
    "load_status",
    "menu_bar_title",
    "record_last_notes_from_recordings",
    "resolve_display_status",
    "run_with_active_reporter",
    "save_last_notes",
    "save_status",
    "seed_last_notes_from_archive",
    "status_touch",
    "_parse_cli_log_progress",
    "_parse_ps_elapsed",
    "_pid_alive",
    "_status_from_cli_pipeline",
]
