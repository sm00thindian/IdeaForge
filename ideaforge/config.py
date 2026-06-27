"""Configuration loading from TOML file, .env, and environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def has_xai_api_key() -> bool:
    key = os.getenv("XAI_API_KEY", "")
    return bool(key and key.strip())


@dataclass
class IdeaForgeConfig:
    archive: Path = field(default_factory=lambda: Path.home() / "IdeaForge")
    llm_backend: str = "auto"  # auto | ollama | grok
    ollama_model: str = "llama3.1"
    grok_model: str = "grok-4.3"
    whisper_backend: str = "auto"  # auto | mlx | faster
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 1
    mode: str = "meeting"
    output_format: str = "both"  # md | json | both
    diarize: bool = False
    min_file_size_bytes: int = 50_000
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
        if "llm" in data:
            llm = data["llm"]
            cfg.llm_backend = llm.get("backend", cfg.llm_backend)
            cfg.ollama_model = llm.get("ollama_model", cfg.ollama_model)
            cfg.grok_model = llm.get("grok_model", cfg.grok_model)
        if "whisper" in data:
            w = data["whisper"]
            cfg.whisper_backend = w.get("backend", cfg.whisper_backend)
            cfg.whisper_model = w.get("model", cfg.whisper_model)
            cfg.whisper_device = w.get("device", cfg.whisper_device)
            cfg.whisper_compute_type = w.get("compute_type", cfg.whisper_compute_type)
            cfg.whisper_beam_size = w.get("beam_size", cfg.whisper_beam_size)
        if "processing" in data:
            p = data["processing"]
            cfg.mode = p.get("mode", cfg.mode)
            cfg.output_format = p.get("output_format", cfg.output_format)
            cfg.diarize = p.get("diarize", cfg.diarize)
            cfg.min_file_size_bytes = p.get("min_file_size_bytes", cfg.min_file_size_bytes)
        if "diarization" in data:
            cfg.hf_token = data["diarization"].get("hf_token")
        if "audio_extensions" in data:
            cfg.audio_extensions = data["audio_extensions"]
        return cfg

    def resolve_secrets(self) -> None:
        """Fill HF token from environment if not set in config."""
        if not self.hf_token:
            self.hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

    def resolve_llm_backend(self, cli_override: Optional[str] = None) -> str:
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

        return backend

    def default_config_path(self) -> Path:
        return Path.home() / ".config" / "ideaforge" / "config.toml"