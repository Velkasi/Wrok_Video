"""Chargement de la configuration : default.yaml + override utilisateur APPDATA."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .paths import app_root, user_config_dir


def _default_output_folder() -> Path:
    return Path.home() / "Documents" / "Resume_Wrok"


class OutputConfig(BaseModel):
    """Dossier unique où sont écrits ensemble la vidéo enregistrée (mode Live)
    et le résumé Markdown. Les deux fichiers partagent le même préfixe horodaté
    (ex. `2026-05-09-1430-reunion-foo.mp4` + `2026-05-09-1430-reunion-foo.md`).
    """

    folder: Path = Field(default_factory=_default_output_folder)


class TranscriptionConfig(BaseModel):
    """Configuration du moteur de transcription. Backend pluggable.

    Backends supportés :
      - "whisper" : faster-whisper (small/medium/large-v3/large-v3-turbo)
      - "canary"  : NeMo Canary 1B (canary-1b-flash) — multilingue FR/EN/DE/ES
    """

    backend: str = "whisper"   # 'whisper' | 'canary'
    model: str = "medium"      # variant du backend (voir BACKEND_REGISTRY)
    language: str = "fr"
    # auto : probe CUDA, fallback CPU. cuda : force GPU. cpu : force CPU.
    device: str = "auto"
    # auto : int8 sur CPU, float16 sur GPU. Sinon : int8/int8_float16/float16/float32.
    compute_type: str = "auto"
    # Options Whisper-spécifiques (ignorées par autres backends)
    vad_filter: bool = True
    beam_size: int = 5


# Alias de compat pour code existant qui référence encore WhisperConfig
WhisperConfig = TranscriptionConfig


class OllamaConfig(BaseModel):
    model: str = "llama3.1:8b-instruct-q4_K_M"
    host: str = "127.0.0.1"
    port: int = 11434
    startup_timeout: int = 30
    # GPU/CPU offload (passé en options à chaque chat). -1 = auto (Ollama décide).
    # 999 = forcer toutes les couches sur GPU. 0 = forcer CPU only.
    num_gpu: int = -1
    # 0 = auto (nombre de cores physiques)
    num_thread: int = 0
    # Contexte max (en tokens). 8192 par défaut, 16384 pour transcripts longs.
    num_ctx: int = 8192

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class ScreenConfig(BaseModel):
    enabled: bool = True
    fps: int = 10
    monitor: int = 1


class MicConfig(BaseModel):
    enabled: bool = True
    samplerate: int = 16000
    device: int | None = None


class SystemAudioConfig(BaseModel):
    enabled: bool = True
    samplerate: int = 16000


class RecordingConfig(BaseModel):
    screen: ScreenConfig = Field(default_factory=ScreenConfig)
    mic: MicConfig = Field(default_factory=MicConfig)
    system_audio: SystemAudioConfig = Field(default_factory=SystemAudioConfig)


class PromptsConfig(BaseModel):
    summary_system: str = ""
    summary_user_template: str = ""


class AppConfig(BaseModel):
    output: OutputConfig = Field(default_factory=OutputConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)

    # Compat : `cfg.whisper` continue de marcher (alias vers transcription)
    @property
    def whisper(self) -> TranscriptionConfig:
        return self.transcription


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def default_config_path() -> Path:
    return app_root() / "config" / "default.yaml"


def user_config_path() -> Path:
    return user_config_dir() / "config.yaml"


def load_config() -> AppConfig:
    """Charge default.yaml puis override avec %APPDATA%\\reunion-resume\\config.yaml si présent."""
    base = _load_yaml(default_config_path())
    override = _load_yaml(user_config_path())
    merged = _deep_merge(base, override)
    return AppConfig.model_validate(merged)


def save_user_config(cfg: AppConfig) -> Path:
    """Persiste la config utilisateur dans APPDATA."""
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.model_dump(mode="json"), f, allow_unicode=True, sort_keys=False)
    return path
