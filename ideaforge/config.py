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


def loads_toml(text: str) -> Dict[str, Any]:
    """Parse TOML text on Python 3.10 (tomli) and 3.11+ (tomllib)."""
    if tomllib is not None:
        return tomllib.loads(text)
    try:
        import tomli
    except ImportError as exc:
        raise RuntimeError(
            "TOML parser unavailable — install tomli (Python 3.10) or use Python 3.11+"
        ) from exc
    try:
        return tomli.loads(text)
    except TypeError:
        return tomli.loads(text.encode("utf-8"))


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
class CreativePlatformStyle:
    style_default: str = ""
    style_variations: List[str] = field(default_factory=list)


@dataclass
class CreativeSettings:
    enabled: bool = True
    trigger_phrases: List[str] = field(
        default_factory=lambda: ["song idea", "lyric idea"]
    )
    scan_chars: int = 500
    temperature: float = 0.6
    style_merge: str = "merge"  # merge | memo_wins | pick_first | pick_random
    target_duration_minutes: float = 4.5
    rhyme_scheme: str = "mixed"  # abab | aabb | mixed
    # Second LLM pass to polish lyrics/hooks (extra cost).
    multi_pass: bool = True
    # Number of alternate chorus hooks (0 = only chorus_hook).
    chorus_variant_count: int = 3


@dataclass
class DeviceBinding:
    """Maps a volume label glob to a device profile (``[[devices]]`` in config)."""

    name: str
    mount_glob: str
    profile: str = "z28"
    chunk_mode: Optional[str] = None  # gap | silence | fixed_window | none; overrides [processing]


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
    # Meeting prompt domain pack: general | fed_grc
    meeting_domain: str = "general"
    output_format: str = "both"  # md | json | both
    diarize: bool = False
    min_speakers: Optional[int] = None
    max_speakers: Optional[int] = None
    speaker_map: Dict[str, str] = field(default_factory=dict)
    speaker_library_enabled: bool = True
    speaker_library_auto_apply: bool = True
    speaker_library_auto_learn: bool = True
    speaker_library_match_threshold: float = 0.75
    speaker_library_path: Optional[Path] = None
    sync_enabled: bool = False
    sync_target: str = ""
    sync_after_notes: bool = True
    sync_scope: str = "session"
    sync_extra_args: List[str] = field(default_factory=lambda: ["-az"])
    daemon_poll_interval: float = 5.0
    daemon_settle_seconds: float = 5.0
    daemon_delete_after_copy: bool = True
    daemon_unmount_after_ingest: bool = True
    daemon_notify: bool = True
    daemon_sync_device_clock: bool = True
    daemon_clock_skew_threshold_seconds: float = 60.0
    daemon_log_rotate_enabled: bool = True
    daemon_log_rotate_hour: int = 2
    daemon_log_rotate_minute: int = 0
    daemon_log_rotate_backups: int = 3
    daemon_merged_wav_retain_days: int = 3
    notify_on_failure: bool = False
    export_reminders: bool = False
    export_reminders_list: str = "IdeaForge"
    export_obsidian: bool = False
    export_obsidian_vault: Optional[Path] = None
    export_obsidian_note: str = "IdeaForge/Action Items.md"
    min_file_size_bytes: int = 50_000
    delete_empty_merged_audio: bool = True
    # Skip LLM when transcript is empty/junk (not a failure; saves API cost).
    llm_gate_enabled: bool = True
    llm_min_transcript_chars: int = 40
    llm_min_transcript_words: int = 8
    llm_max_repeat_word_ratio: float = 0.65  # 0 disables
    llm_min_unique_word_ratio: float = 0.12  # 0 disables
    merge_chunks: bool = True
    # After a successful multi-chunk session, encode *_merged.wav → *_merged.mp3
    # and drop the large WAV (sources stay WAV until purged separately).
    merge_to_mp3: bool = True
    merge_mp3_bitrate: str = "64k"
    chunk_mode: str = "gap"  # gap | silence | fixed_window | none
    chunk_gap_seconds: float = 30.0
    merge_min_chunk_seconds: float = 600.0
    # Cap multi-chunk merges so ML stays under Apple Metal's ~4 GiB buffer.
    # Overnight leave-on recorders otherwise become one multi-hour session.
    max_session_seconds: float = 4 * 3600.0  # 4 hours; 0 disables
    split_silence_seconds: float = 3.0
    split_window_seconds: float = 900.0
    normalize_audio: bool = True
    max_parallel_sessions: int = 1
    hf_token: Optional[str] = None
    audio_extensions: List[str] = field(
        default_factory=lambda: [".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".wma", ".opus"]
    )
    creative_enabled: bool = True
    creative_trigger_phrases: List[str] = field(
        default_factory=lambda: ["song idea", "lyric idea"]
    )
    creative_scan_chars: int = 500
    creative_temperature: float = 0.6
    creative_style_merge: str = "merge"
    creative_target_duration_minutes: float = 4.5
    creative_rhyme_scheme: str = "mixed"
    creative_multi_pass: bool = True
    creative_chorus_variant_count: int = 3
    creative_suno_style_default: str = ""
    creative_suno_style_variations: List[str] = field(default_factory=list)
    creative_udio_style_default: str = ""
    creative_udio_style_variations: List[str] = field(default_factory=list)

    @classmethod
    def from_toml(cls, path: Path) -> "IdeaForgeConfig":
        cfg = cls()
        if not path.exists():
            return cfg
        data = loads_toml(path.read_text(encoding="utf-8"))
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
                    chunk_mode=str(entry["chunk_mode"]) if entry.get("chunk_mode") else None,
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
            if "meeting_domain" in p:
                cfg.meeting_domain = str(p["meeting_domain"]).strip().lower() or "general"
            cfg.output_format = p.get("output_format", cfg.output_format)
            cfg.diarize = p.get("diarize", cfg.diarize)
            cfg.min_file_size_bytes = p.get("min_file_size_bytes", cfg.min_file_size_bytes)
            if "delete_empty_merged_audio" in p:
                cfg.delete_empty_merged_audio = bool(p["delete_empty_merged_audio"])
            if "llm_gate_enabled" in p:
                cfg.llm_gate_enabled = bool(p["llm_gate_enabled"])
            if "llm_min_transcript_chars" in p:
                cfg.llm_min_transcript_chars = max(0, int(p["llm_min_transcript_chars"]))
            if "llm_min_transcript_words" in p:
                cfg.llm_min_transcript_words = max(0, int(p["llm_min_transcript_words"]))
            if "llm_max_repeat_word_ratio" in p:
                cfg.llm_max_repeat_word_ratio = float(p["llm_max_repeat_word_ratio"])
            if "llm_min_unique_word_ratio" in p:
                cfg.llm_min_unique_word_ratio = float(p["llm_min_unique_word_ratio"])
            if "merge_chunks" in p:
                cfg.merge_chunks = bool(p["merge_chunks"])
            if "merge_to_mp3" in p:
                cfg.merge_to_mp3 = bool(p["merge_to_mp3"])
            if "merge_mp3_bitrate" in p:
                cfg.merge_mp3_bitrate = str(p["merge_mp3_bitrate"])
            if "chunk_gap_seconds" in p:
                cfg.chunk_gap_seconds = float(p["chunk_gap_seconds"])
            if "merge_min_chunk_seconds" in p:
                cfg.merge_min_chunk_seconds = float(p["merge_min_chunk_seconds"])
            if "max_session_seconds" in p:
                cfg.max_session_seconds = float(p["max_session_seconds"])
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
            if "library_enabled" in speakers:
                cfg.speaker_library_enabled = bool(speakers["library_enabled"])
            if "library_auto_apply" in speakers:
                cfg.speaker_library_auto_apply = bool(speakers["library_auto_apply"])
            if "library_auto_learn" in speakers:
                cfg.speaker_library_auto_learn = bool(speakers["library_auto_learn"])
            if "library_match_threshold" in speakers:
                cfg.speaker_library_match_threshold = float(speakers["library_match_threshold"])
            if "library_path" in speakers:
                cfg.speaker_library_path = Path(speakers["library_path"]).expanduser()
        if "sync" in data:
            sync = data["sync"]
            cfg.sync_enabled = bool(sync.get("enabled", cfg.sync_enabled))
            cfg.sync_target = str(sync.get("target", cfg.sync_target))
            cfg.sync_after_notes = bool(sync.get("after_notes", cfg.sync_after_notes))
            cfg.sync_scope = str(sync.get("scope", cfg.sync_scope))
            if "extra_args" in sync:
                cfg.sync_extra_args = [str(arg) for arg in sync["extra_args"]]
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
            if "log_rotate_enabled" in daemon:
                cfg.daemon_log_rotate_enabled = bool(daemon["log_rotate_enabled"])
            if "log_rotate_hour" in daemon:
                cfg.daemon_log_rotate_hour = int(daemon["log_rotate_hour"])
            if "log_rotate_minute" in daemon:
                cfg.daemon_log_rotate_minute = int(daemon["log_rotate_minute"])
            if "log_rotate_backups" in daemon:
                cfg.daemon_log_rotate_backups = int(daemon["log_rotate_backups"])
            if "merged_wav_retain_days" in daemon:
                cfg.daemon_merged_wav_retain_days = int(daemon["merged_wav_retain_days"])
        if "export" in data:
            export = data["export"]
            cfg.export_reminders = bool(export.get("reminders", cfg.export_reminders))
            cfg.export_reminders_list = export.get("reminders_list", cfg.export_reminders_list)
            cfg.export_obsidian = bool(export.get("obsidian", cfg.export_obsidian))
            if "obsidian_vault" in export:
                cfg.export_obsidian_vault = Path(export["obsidian_vault"]).expanduser()
            cfg.export_obsidian_note = export.get("obsidian_note", cfg.export_obsidian_note)
        if "creative" in data:
            creative = data["creative"]
            if "enabled" in creative:
                cfg.creative_enabled = bool(creative["enabled"])
            if "trigger_phrases" in creative:
                cfg.creative_trigger_phrases = [
                    str(p) for p in creative["trigger_phrases"]
                ]
            if "scan_chars" in creative:
                cfg.creative_scan_chars = int(creative["scan_chars"])
            if "temperature" in creative:
                cfg.creative_temperature = float(creative["temperature"])
            if "style_merge" in creative:
                cfg.creative_style_merge = str(creative["style_merge"])
            if "target_duration_minutes" in creative:
                cfg.creative_target_duration_minutes = float(
                    creative["target_duration_minutes"]
                )
            if "rhyme_scheme" in creative:
                cfg.creative_rhyme_scheme = str(creative["rhyme_scheme"])
            if "multi_pass" in creative:
                cfg.creative_multi_pass = bool(creative["multi_pass"])
            if "chorus_variant_count" in creative:
                cfg.creative_chorus_variant_count = max(
                    0, int(creative["chorus_variant_count"])
                )
            suno = creative.get("suno")
            if isinstance(suno, dict):
                if "style_default" in suno:
                    cfg.creative_suno_style_default = str(suno["style_default"])
                if "style_variations" in suno:
                    cfg.creative_suno_style_variations = [
                        str(v) for v in suno["style_variations"]
                    ]
            udio = creative.get("udio")
            if isinstance(udio, dict):
                if "style_default" in udio:
                    cfg.creative_udio_style_default = str(udio["style_default"])
                if "style_variations" in udio:
                    cfg.creative_udio_style_variations = [
                        str(v) for v in udio["style_variations"]
                    ]
        return cfg

    def transcript_gate_settings(self) -> "TranscriptGateSettings":
        from ideaforge.transcript_gate import TranscriptGateSettings

        return TranscriptGateSettings(
            enabled=self.llm_gate_enabled,
            min_chars=self.llm_min_transcript_chars,
            min_words=self.llm_min_transcript_words,
            max_repeat_word_ratio=self.llm_max_repeat_word_ratio,
            min_unique_word_ratio=self.llm_min_unique_word_ratio,
        )

    def creative_settings(self) -> CreativeSettings:
        return CreativeSettings(
            enabled=self.creative_enabled,
            trigger_phrases=list(self.creative_trigger_phrases),
            scan_chars=self.creative_scan_chars,
            temperature=self.creative_temperature,
            style_merge=self.creative_style_merge,
            target_duration_minutes=self.creative_target_duration_minutes,
            rhyme_scheme=self.creative_rhyme_scheme,
            multi_pass=self.creative_multi_pass,
            chorus_variant_count=self.creative_chorus_variant_count,
        )

    def creative_suno_style(self) -> CreativePlatformStyle:
        return CreativePlatformStyle(
            style_default=self.creative_suno_style_default,
            style_variations=list(self.creative_suno_style_variations),
        )

    def creative_udio_style(self) -> CreativePlatformStyle:
        return CreativePlatformStyle(
            style_default=self.creative_udio_style_default,
            style_variations=list(self.creative_udio_style_variations),
        )

    def sync_settings(self) -> "SyncSettings":
        from ideaforge.remote_sync import SyncSettings

        return SyncSettings(
            enabled=self.sync_enabled,
            target=self.sync_target,
            after_notes=self.sync_after_notes,
            scope=self.sync_scope,  # type: ignore[arg-type]
            extra_args=list(self.sync_extra_args),
        )

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