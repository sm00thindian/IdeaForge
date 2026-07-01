"""Config schema and value validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

from ideaforge.config import IdeaForgeConfig, loads_toml

TOP_LEVEL_KEYS: Set[str] = {
    "archive",
    "devices",
    "llm",
    "whisper",
    "processing",
    "diarization",
    "speakers",
    "daemon",
    "export",
    "sync",
    "audio_extensions",
}

SECTION_KEYS: Dict[str, Set[str]] = {
    "llm": {"backend", "ollama_model", "grok_model", "claude_model"},
    "whisper": {
        "backend",
        "model",
        "device",
        "compute_type",
        "beam_size",
        "language",
    },
    "processing": {
        "mode",
        "output_format",
        "diarize",
        "min_file_size_bytes",
        "merge_chunks",
        "chunk_mode",
        "chunk_gap_seconds",
        "merge_min_chunk_seconds",
        "split_silence_seconds",
        "split_window_seconds",
        "normalize_audio",
        "max_parallel_sessions",
    },
    "diarization": {"hf_token", "min_speakers", "max_speakers"},
    "speakers": {
        "map",
        "names",
        "library_enabled",
        "library_auto_apply",
        "library_auto_learn",
        "library_match_threshold",
        "library_path",
    },
    "daemon": {
        "poll_interval_seconds",
        "settle_seconds",
        "delete_after_copy",
        "unmount_after_ingest",
        "notify",
        "sync_device_clock",
        "clock_skew_threshold_seconds",
        "notify_on_failure",
    },
    "export": {
        "reminders",
        "reminders_list",
        "obsidian",
        "obsidian_vault",
        "obsidian_note",
    },
    "sync": {
        "enabled",
        "target",
        "after_notes",
        "scope",
        "extra_args",
    },
}

DEVICE_PROFILES = {"z28", "generic_wav"}
CHUNK_MODES = {"gap", "silence", "fixed_window", "none"}
SYNC_SCOPES = {"session", "device", "archive"}

LLM_BACKENDS = {"auto", "ollama", "grok", "claude"}
WHISPER_BACKENDS = {"auto", "mlx", "faster"}
WHISPER_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
MODES = {"meeting", "creative", "auto"}
OUTPUT_FORMATS = {"md", "json", "both"}


class ConfigValidationError(ValueError):
    """Raised when config.toml contains invalid or unknown settings."""


def find_unknown_keys(data: Mapping[str, Any]) -> List[str]:
    """Return human-readable errors for unrecognized config keys."""
    issues: List[str] = []
    for key in data:
        if key not in TOP_LEVEL_KEYS:
            issues.append(f"unknown top-level key '{key}'")
    for section, allowed in SECTION_KEYS.items():
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for key in block:
            if key not in allowed:
                issues.append(f"unknown [{section}] key '{key}'")
    return issues


def validate_config_values(cfg: IdeaForgeConfig) -> List[str]:
    """Return errors for invalid enum/range values on a merged config."""
    issues: List[str] = []

    if cfg.llm_backend not in LLM_BACKENDS:
        issues.append(f"invalid llm.backend '{cfg.llm_backend}' (expected one of {sorted(LLM_BACKENDS)})")
    if cfg.whisper_backend not in WHISPER_BACKENDS:
        issues.append(
            f"invalid whisper.backend '{cfg.whisper_backend}' "
            f"(expected one of {sorted(WHISPER_BACKENDS)})"
        )
    if cfg.whisper_model not in WHISPER_MODELS:
        issues.append(
            f"invalid whisper.model '{cfg.whisper_model}' "
            f"(expected one of {sorted(WHISPER_MODELS)})"
        )
    if cfg.mode not in MODES:
        issues.append(f"invalid processing.mode '{cfg.mode}' (expected one of {sorted(MODES)})")
    if cfg.output_format not in OUTPUT_FORMATS:
        issues.append(
            f"invalid processing.output_format '{cfg.output_format}' "
            f"(expected one of {sorted(OUTPUT_FORMATS)})"
        )
    if cfg.daemon_poll_interval <= 0:
        issues.append("daemon.poll_interval_seconds must be > 0")
    if cfg.daemon_settle_seconds < 0:
        issues.append("daemon.settle_seconds must be >= 0")
    if cfg.daemon_clock_skew_threshold_seconds < 0:
        issues.append("daemon.clock_skew_threshold_seconds must be >= 0")
    if cfg.max_parallel_sessions < 1:
        issues.append("processing.max_parallel_sessions must be >= 1")
    if cfg.min_file_size_bytes < 0:
        issues.append("processing.min_file_size_bytes must be >= 0")
    if cfg.chunk_gap_seconds < 0:
        issues.append("processing.chunk_gap_seconds must be >= 0")
    if cfg.merge_min_chunk_seconds < 0:
        issues.append("processing.merge_min_chunk_seconds must be >= 0")
    if cfg.chunk_mode not in CHUNK_MODES:
        issues.append(
            f"invalid processing.chunk_mode '{cfg.chunk_mode}' "
            f"(expected one of {sorted(CHUNK_MODES)})"
        )
    if cfg.split_silence_seconds <= 0:
        issues.append("processing.split_silence_seconds must be > 0")
    if cfg.split_window_seconds <= 0:
        issues.append("processing.split_window_seconds must be > 0")
    if cfg.speaker_library_match_threshold <= 0 or cfg.speaker_library_match_threshold > 1:
        issues.append("speakers.library_match_threshold must be in (0, 1]")
    if cfg.sync_scope not in SYNC_SCOPES:
        issues.append(
            f"invalid sync.scope '{cfg.sync_scope}' (expected one of {sorted(SYNC_SCOPES)})"
        )
    if cfg.sync_enabled and not cfg.sync_target.strip():
        issues.append("sync.target must be set when sync.enabled = true")

    device_names: Set[str] = set()
    for device in cfg.devices:
        if not device.name.strip():
            issues.append("devices[].name must not be empty")
        elif device.name in device_names:
            issues.append(f"duplicate devices[].name '{device.name}'")
        else:
            device_names.add(device.name)
        if not device.mount_glob.strip():
            issues.append(f"devices[{device.name!r}].mount_glob must not be empty")
        if device.profile not in DEVICE_PROFILES:
            issues.append(
                f"devices[{device.name!r}].profile '{device.profile}' "
                f"(expected one of {sorted(DEVICE_PROFILES)})"
            )
        if device.chunk_mode is not None and device.chunk_mode not in CHUNK_MODES:
            issues.append(
                f"devices[{device.name!r}].chunk_mode '{device.chunk_mode}' "
                f"(expected one of {sorted(CHUNK_MODES)})"
            )

    return issues


def validate_config_paths(cfg: IdeaForgeConfig) -> List[str]:
    """Return errors for archive/export paths that cannot be used."""
    issues: List[str] = []
    archive = cfg.archive.expanduser()
    parent = archive.parent
    if parent != Path("/") and not parent.exists():
        issues.append(f"archive parent does not exist: {parent}")
    elif not archive.exists():
        try:
            archive.mkdir(parents=True, exist_ok=True)
        except OSError:
            issues.append(f"archive path is not creatable: {archive}")

    if cfg.export_obsidian and cfg.export_obsidian_vault is not None:
        vault = cfg.export_obsidian_vault.expanduser()
        if not vault.exists():
            issues.append(f"export.obsidian_vault does not exist: {vault}")

    return issues


def validate_config(
    cfg: IdeaForgeConfig,
    *,
    raw_data: Optional[Mapping[str, Any]] = None,
    check_paths: bool = True,
) -> None:
    """Validate config; raise ConfigValidationError on problems."""
    issues: List[str] = []
    if raw_data is not None:
        issues.extend(find_unknown_keys(raw_data))
    issues.extend(validate_config_values(cfg))
    if check_paths:
        issues.extend(validate_config_paths(cfg))
    if issues:
        raise ConfigValidationError("\n".join(f"  • {item}" for item in issues))


def validate_config_file(path: Path, *, check_paths: bool = True) -> IdeaForgeConfig:
    """Load and validate config.toml; raise ConfigValidationError on failure."""
    if not path.is_file():
        raise ConfigValidationError(f"config file not found: {path}")

    try:
        raw = loads_toml(path.read_text(encoding="utf-8"))
    except RuntimeError as exc:
        raise ConfigValidationError(str(exc)) from exc
    cfg = IdeaForgeConfig()
    cfg = IdeaForgeConfig._merge(cfg, raw)
    validate_config(cfg, raw_data=raw, check_paths=check_paths)
    return cfg