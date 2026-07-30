"""Config schema and value validation."""

from __future__ import annotations

import os
import shutil
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
    "creative",
    "audio_extensions",
}

CREATIVE_SECTION_KEYS: Set[str] = {
    "enabled",
    "trigger_phrases",
    "scan_chars",
    "temperature",
    "style_merge",
    "target_duration_minutes",
    "rhyme_scheme",
    "multi_pass",
    "chorus_variant_count",
    "suno",
    "udio",
}

RHYME_SCHEMES = {"abab", "aabb", "mixed"}

CREATIVE_PLATFORM_KEYS: Set[str] = {"style_default", "style_variations"}

STYLE_MERGE_STRATEGIES = {"merge", "memo_wins", "pick_first", "pick_random"}

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
        "delete_empty_merged_audio",
        "llm_gate_enabled",
        "llm_min_transcript_chars",
        "llm_min_transcript_words",
        "llm_max_repeat_word_ratio",
        "llm_min_unique_word_ratio",
        "merge_chunks",
        "merge_to_mp3",
        "merge_mp3_bitrate",
        "chunk_mode",
        "chunk_gap_seconds",
        "merge_min_chunk_seconds",
        "max_session_seconds",
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
        "log_rotate_enabled",
        "log_rotate_hour",
        "log_rotate_minute",
        "log_rotate_backups",
        "merged_wav_retain_days",
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

    creative = data.get("creative")
    if isinstance(creative, dict):
        for key in creative:
            if key not in CREATIVE_SECTION_KEYS:
                issues.append(f"unknown [creative] key '{key}'")
        for platform_key in ("suno", "udio"):
            platform = creative.get(platform_key)
            if isinstance(platform, dict):
                for key in platform:
                    if key not in CREATIVE_PLATFORM_KEYS:
                        issues.append(f"unknown [creative.{platform_key}] key '{key}'")
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
    if not 0 <= cfg.daemon_log_rotate_hour <= 23:
        issues.append("daemon.log_rotate_hour must be between 0 and 23")
    if not 0 <= cfg.daemon_log_rotate_minute <= 59:
        issues.append("daemon.log_rotate_minute must be between 0 and 59")
    if cfg.daemon_log_rotate_backups < 1:
        issues.append("daemon.log_rotate_backups must be >= 1")
    if cfg.daemon_merged_wav_retain_days < 0:
        issues.append("daemon.merged_wav_retain_days must be >= 0 (0 disables prune)")
    if cfg.max_parallel_sessions < 1:
        issues.append("processing.max_parallel_sessions must be >= 1")
    if cfg.min_file_size_bytes < 0:
        issues.append("processing.min_file_size_bytes must be >= 0")
    if cfg.llm_min_transcript_chars < 0:
        issues.append("processing.llm_min_transcript_chars must be >= 0")
    if cfg.llm_min_transcript_words < 0:
        issues.append("processing.llm_min_transcript_words must be >= 0")
    if not 0.0 <= cfg.llm_max_repeat_word_ratio <= 1.0:
        issues.append("processing.llm_max_repeat_word_ratio must be between 0.0 and 1.0")
    if not 0.0 <= cfg.llm_min_unique_word_ratio <= 1.0:
        issues.append("processing.llm_min_unique_word_ratio must be between 0.0 and 1.0")
    if cfg.chunk_gap_seconds < 0:
        issues.append("processing.chunk_gap_seconds must be >= 0")
    if cfg.merge_min_chunk_seconds < 0:
        issues.append("processing.merge_min_chunk_seconds must be >= 0")
    if cfg.max_session_seconds < 0:
        issues.append("processing.max_session_seconds must be >= 0 (0 disables cap)")
    bitrate = cfg.merge_mp3_bitrate.strip().lower()
    if cfg.merge_to_mp3 and not bitrate:
        issues.append("processing.merge_mp3_bitrate must be non-empty when merge_to_mp3 is true")
    elif bitrate and not (
        bitrate.endswith("k") and bitrate[:-1].isdigit()
    ) and not bitrate.isdigit():
        # Accept "64k", "128k", or bare "64"
        issues.append(
            "processing.merge_mp3_bitrate must look like '64k' or '128' "
            f"(got {cfg.merge_mp3_bitrate!r})"
        )
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
    if cfg.creative_scan_chars < 50:
        issues.append("creative.scan_chars must be >= 50")
    if not 0.0 <= cfg.creative_temperature <= 2.0:
        issues.append("creative.temperature must be between 0.0 and 2.0")
    if cfg.creative_style_merge not in STYLE_MERGE_STRATEGIES:
        issues.append(
            f"invalid creative.style_merge '{cfg.creative_style_merge}' "
            f"(expected one of {sorted(STYLE_MERGE_STRATEGIES)})"
        )
    if cfg.creative_enabled and not cfg.creative_trigger_phrases:
        issues.append("creative.trigger_phrases must not be empty when creative.enabled = true")
    if cfg.creative_target_duration_minutes <= 0:
        issues.append("creative.target_duration_minutes must be > 0")
    if cfg.creative_rhyme_scheme not in RHYME_SCHEMES:
        issues.append(
            f"invalid creative.rhyme_scheme '{cfg.creative_rhyme_scheme}' "
            f"(expected one of {sorted(RHYME_SCHEMES)})"
        )
    if cfg.creative_chorus_variant_count < 0:
        issues.append("creative.chorus_variant_count must be >= 0")
    if cfg.creative_chorus_variant_count > 8:
        issues.append("creative.chorus_variant_count must be <= 8")

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


def _tool_on_path(name: str) -> Optional[str]:
    found = shutil.which(name)
    return found


def collect_runtime_warnings(cfg: IdeaForgeConfig) -> List[str]:
    """Soft environment checks operators should fix before long daemon runs.

    These are warnings (not schema errors): missing tools/keys degrade features
    rather than making config.toml invalid.
    """
    from ideaforge.config import has_anthropic_api_key, has_xai_api_key

    warnings: List[str] = []
    if not _tool_on_path("ffmpeg"):
        if cfg.merge_to_mp3:
            warnings.append(
                "ffmpeg not found on PATH — processing.merge_to_mp3 will be skipped "
                "(install ffmpeg; re-run ./scripts/install-daemon.sh so LaunchAgent PATH includes Homebrew)"
            )
        if cfg.normalize_audio:
            warnings.append(
                "ffmpeg not found on PATH — processing.normalize_audio cannot convert "
                "MP3/FLAC (WAV-only ingest still works)"
            )
        if cfg.chunk_mode in ("silence", "fixed_window"):
            warnings.append(
                f"ffmpeg not found on PATH — processing.chunk_mode={cfg.chunk_mode!r} "
                "requires ffmpeg"
            )
    if cfg.sync_enabled and not _tool_on_path("rsync"):
        warnings.append(
            "rsync not found on PATH — sync.enabled jobs will fail "
            "(install rsync or disable [sync])"
        )

    hf_token = (
        (cfg.hf_token or "").strip()
        or (os.environ.get("HF_TOKEN") or "").strip()
        or (os.environ.get("HUGGINGFACE_TOKEN") or "").strip()
    )
    if cfg.diarize and not hf_token:
        warnings.append(
            "processing.diarize is true but HF_TOKEN is not set — "
            "pyannote diarization will fail (set hf_token or HF_TOKEN, then reinstall daemon)"
        )

    backend = (cfg.llm_backend or "auto").strip().lower()
    if backend == "grok" and not has_xai_api_key():
        warnings.append(
            "llm.backend is 'grok' but XAI_API_KEY is not set — "
            "export the key and re-run ./scripts/install-daemon.sh"
        )
    elif backend == "claude" and not has_anthropic_api_key():
        warnings.append(
            "llm.backend is 'claude' but ANTHROPIC_API_KEY is not set — "
            "export the key and re-run ./scripts/install-daemon.sh"
        )
    elif backend == "auto" and not has_xai_api_key():
        warnings.append(
            "XAI_API_KEY not set — llm.backend=auto will use Ollama (local). "
            "Set XAI_API_KEY for Grok and reinstall the daemon to snapshot the key."
        )

    return warnings


def print_runtime_warnings(warnings: List[str], *, stream=None) -> None:
    """Print runtime warnings to stdout (or stream)."""
    import sys

    out = stream or sys.stdout
    for item in warnings:
        print(f"⚠️  {item}", file=out)


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


def validate_config_file(
    path: Path,
    *,
    check_paths: bool = True,
    check_runtime: bool = False,
) -> IdeaForgeConfig:
    """Load and validate config.toml; raise ConfigValidationError on failure.

    When ``check_runtime`` is true, print soft environment warnings (ffmpeg, keys)
    but do not fail validation solely because of them.
    """
    if not path.is_file():
        raise ConfigValidationError(f"config file not found: {path}")

    try:
        raw = loads_toml(path.read_text(encoding="utf-8"))
    except RuntimeError as exc:
        raise ConfigValidationError(str(exc)) from exc
    cfg = IdeaForgeConfig()
    cfg = IdeaForgeConfig._merge(cfg, raw)
    validate_config(cfg, raw_data=raw, check_paths=check_paths)
    if check_runtime:
        warnings = collect_runtime_warnings(cfg)
        print_runtime_warnings(warnings)
    return cfg