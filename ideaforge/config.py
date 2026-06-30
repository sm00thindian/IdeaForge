"""Configuration loading from TOML file, .env, and environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

LlmBackend = Literal["auto", "ollama", "grok", "claude"]
WhisperBackend = Literal["auto", "mlx", "faster"]
ProcessingMode = Literal["meeting", "creative", "auto"]
OutputFormat = Literal["md", "json", "both"]

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None  # type: ignore


def find_dotenv() -> Optional[Path]:
    """Locate .env in cwd or repository root."""
    for candidate in (Path.cwd() / ".env", _PACKAGE_ROOT / ".env"):
        if candidate.is_file():
            return candidate
    return None


def load_dotenv(path: Optional[Path] = None) -> Optional[Path]:
    """
    Load KEY=VALUE pairs from a .env file into os.environ.
    Existing environment variables are not overwritten.
    """
    dotenv_path = path or find_dotenv()
    if dotenv_path is None:
        return None

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)

    return dotenv_path


def _hf_login(token: str) -> None:
    """Register HF token with huggingface_hub (best-effort, non-fatal)."""
    if not token:
        return
    try:
        from huggingface_hub import login  # type: ignore

        login(token=token, add_to_git_credential=False)
    except Exception:
        pass


def has_xai_api_key() -> bool:
    key = os.getenv("XAI_API_KEY", "")
    return bool(key and key.strip())


def has_anthropic_api_key() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(key and key.strip())


@dataclass
class DeviceBinding:
    """Maps a volume label glob to a device profile (``[[devices]]`` in config)."""

    name: str
    mount_glob: str
    profile: str = "z28"


@dataclass
class IdeaForgeConfig:
    archive: Path = field(default_factory=lambda: Path.home() / "IdeaForge")
    devices: List[DeviceBinding] = field(default_factory=list)
    llm_backend: str = "auto"  # auto | ollama | grok | claude
    ollama_model: str = "llama3.1"
    grok_model: str = "grok-4.3"
    claude_model: str = "claude-sonnet-4-20250514"
    whisper_backend: str = "auto"  # auto | mlx | faster
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 1
    whisper_language: Optional[str] = None
    mode: str = "meeting"
    output_format: str = "both"  # md | json | both
    diarize: bool = False
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None
    speaker_map: Dict[str, str] = field(default_factory=dict)
    daemon_poll_interval: float = 5.0
    daemon_settle_seconds: float = 5.0
    daemon_delete_after_copy: bool = True
    daemon_unmount_after_ingest: bool = True
    daemon_notify: bool = True
    daemon_sync_device_clock: bool = True
    daemon_clock_skew_threshold_seconds: float = 60.0
    notify_on_failure: bool = False
    export_reminders: bool = False
    export_reminders_list: str = "IdeaForge"
    export_obsidian: bool = False
    export_obsidian_vault: Optional[Path] = None
    export_obsidian_note: str = "IdeaForge/Action Items.md"
    min_file_size_bytes: int = 50_000
    merge_chunks: bool = True
    chunk_mode: str = "gap"  # gap | silence | fixed_window | none
    chunk_gap_seconds: float = 30.0
    merge_min_chunk_seconds: float = 600.0
    split_silence_seconds: float = 3.0
    split_window_seconds: float = 900.0
    normalize_audio: bool = True
    max_parallel_sessions: int = 1
    hf_token: Optional[str] = None
    audio_extensions: List[str] = field(
        default_factory=lambda: [".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".opus"]
    )

    @classmethod
    def from_toml(cls, path: Path) -> "IdeaForgeConfig":
        cfg = cls()
        if not path.exists() or tomllib is None:
            return cfg
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls._merge(cfg, data)

    @classmethod
    def _merge(cls, cfg: "IdeaForgeConfig", data: Dict[str, Any]) -> "IdeaForgeConfig":
        if "archive" in data:
            cfg.archive = Path(data["archive"]).expanduser()
        if "devices" in data:
            cfg.devices = [
                DeviceBinding(
                    name=str(entry["name"]),
                    mount_glob=str(entry["mount_glob"]),
                    profile=str(entry.get("profile", "z28")),
                )
                for entry in data["devices"]
                if isinstance(entry, dict) and "name" in entry and "mount_glob" in entry
            ]
        if "llm" in data:
            llm = data["llm"]
            cfg.llm_backend = llm.get("backend", cfg.llm_backend)
            cfg.ollama_model = llm.get("ollama_model", cfg.ollama_model)
            cfg.grok_model = llm.get("grok_model", cfg.grok_model)
            cfg.claude_model = llm.get("claude_model", cfg.claude_model)
        if "whisper" in data:
            w = data["whisper"]
            cfg.whisper_backend = w.get("backend", cfg.whisper_backend)
            cfg.whisper_model = w.get("model", cfg.whisper_model)
            cfg.whisper_device = w.get("device", cfg.whisper_device)
            cfg.whisper_compute_type = w.get("compute_type", cfg.whisper_compute_type)
            cfg.whisper_beam_size = w.get("beam_size", cfg.whisper_beam_size)
            lang = w.get("language")
            if lang is not None:
                cfg.whisper_language = str(lang) if lang else None
        if "processing" in data:
            p = data["processing"]
            cfg.mode = p.get("mode", cfg.mode)
            cfg.output_format = p.get("output_format", cfg.output_format)
            cfg.diarize = p.get("diarize", cfg.diarize)
            cfg.min_file_size_bytes = p.get("min_file_size_bytes", cfg.min_file_size_bytes)
            if "merge_chunks" in p:
                cfg.merge_chunks = bool(p["merge_chunks"])
            if "chunk_gap_seconds" in p:
                cfg.chunk_gap_seconds = float(p["chunk_gap_seconds"])
            if "merge_min_chunk_seconds" in p:
                cfg.merge_min_chunk_seconds = float(p["merge_min_chunk_seconds"])
            if "chunk_mode" in p:
                cfg.chunk_mode = str(p["chunk_mode"])
            if "split_silence_seconds" in p:
                cfg.split_silence_seconds = float(p["split_silence_seconds"])
            if "split_window_seconds" in p:
                cfg.split_window_seconds = float(p["split_window_seconds"])
            if "normalize_audio" in p:
                cfg.normalize_audio = bool(p["normalize_audio"])
            if "max_parallel_sessions" in p:
                cfg.max_parallel_sessions = max(1, int(p["max_parallel_sessions"]))
        if "diarization" in data:
            d = data["diarization"]
            cfg.hf_token = d.get("hf_token")
            cfg.min_speakers = d.get("min_speakers")
            cfg.max_speakers = d.get("max_speakers")
        if "speakers" in data:
            speakers = data["speakers"]
            if "map" in speakers:
                cfg.speaker_map = {str(k): str(v) for k, v in speakers["map"].items()}
            elif "names" in speakers:
                cfg.speaker_map = {str(k): str(v) for k, v in speakers["names"].items()}
        if "audio_extensions" in data:
            cfg.audio_extensions = data["audio_extensions"]
        if "daemon" in data:
            daemon = data["daemon"]
            cfg.daemon_poll_interval = float(
                daemon.get("poll_interval_seconds", cfg.daemon_poll_interval)
            )
            cfg.daemon_settle_seconds = float(
                daemon.get("settle_seconds", cfg.daemon_settle_seconds)
            )
            if "delete_after_copy" in daemon:
                cfg.daemon_delete_after_copy = bool(daemon["delete_after_copy"])
            if "unmount_after_ingest" in daemon:
                cfg.daemon_unmount_after_ingest = bool(daemon["unmount_after_ingest"])
            if "notify" in daemon:
                cfg.daemon_notify = bool(daemon["notify"])
            if "sync_device_clock" in daemon:
                cfg.daemon_sync_device_clock = bool(daemon["sync_device_clock"])
            if "clock_skew_threshold_seconds" in daemon:
                cfg.daemon_clock_skew_threshold_seconds = float(
                    daemon["clock_skew_threshold_seconds"]
                )
            if "notify_on_failure" in daemon:
                cfg.notify_on_failure = bool(daemon["notify_on_failure"])
        if "export" in data:
            export = data["export"]
            cfg.export_reminders = bool(export.get("reminders", cfg.export_reminders))
            cfg.export_reminders_list = export.get("reminders_list", cfg.export_reminders_list)
            cfg.export_obsidian = bool(export.get("obsidian", cfg.export_obsidian))
            if "obsidian_vault" in export:
                cfg.export_obsidian_vault = Path(export["obsidian_vault"]).expanduser()
            cfg.export_obsidian_note = export.get("obsidian_note", cfg.export_obsidian_note)
        return cfg

    def export_settings(self, *, force: bool = False) -> "ExportSettings":
        from ideaforge.export import ExportSettings

        return ExportSettings(
            reminders=self.export_reminders,
            reminders_list=self.export_reminders_list,
            obsidian=self.export_obsidian,
            obsidian_vault=self.export_obsidian_vault,
            obsidian_note=self.export_obsidian_note,
            force=force,
        )

    def resolve_secrets(self) -> None:
        """Fill HF token from environment if not set in config."""
        if not self.hf_token:
            self.hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        if self.hf_token:
            _hf_login(self.hf_token.strip())

    def resolve_llm_backend(self, cli_override: Optional[str] = None) -> LlmBackend:
        """Pick LLM backend: CLI flag > config > auto-detect XAI_API_KEY."""
        if cli_override:
            backend = cli_override
        else:
            backend = self.llm_backend

        if backend == "auto":
            if has_xai_api_key():
                return "grok"
            return "ollama"

        if backend == "grok" and not has_xai_api_key():
            print("    ⚠️  XAI_API_KEY not set — falling back to Ollama")
            return "ollama"

        if backend == "claude" and not has_anthropic_api_key():
            print("    ⚠️  ANTHROPIC_API_KEY not set — falling back to Ollama")
            return "ollama"

        return backend

    def default_config_path(self) -> Path:
        return Path.home() / ".config" / "ideaforge" / "config.toml"