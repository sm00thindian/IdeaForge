"""Config schema and value validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None  # type: ignore

from ideaforge.config import IdeaForgeConfig

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
    "speakers": {"map", "names"},
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
}

DEVICE_PROFILES = {"z28", "generic_wav"}
CHUNK_MODES = {"gap", "silence", "fixed_window", "none"}

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
    if tomllib is None:
        raise ConfigValidationError("tomllib is unavailable (Python 3.11+ required)")
    if not path.is_file():
        raise ConfigValidationError(f"config file not found: {path}")

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    cfg = IdeaForgeConfig()
    cfg = IdeaForgeConfig._merge(cfg, raw)
    validate_config(cfg, raw_data=raw, check_paths=check_paths)
    return cfg