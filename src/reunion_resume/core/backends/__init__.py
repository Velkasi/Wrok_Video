"""Backends de transcription pluggables.

Chaque backend implémente le Protocol `TranscriptionBackend` :
  - `name()` : identifiant court (utilisé dans config + GUI)
  - `transcribe(audio_path, progress_cb) -> TranscriptionResult`

Backends fournis :
  - `whisper`  : faster-whisper (CTranslate2) — Whisper small/medium/large-v3/turbo
  - `canary`   : NeMo Canary 1B (multilingue FR/EN/DE/ES, NVIDIA NeMo) — extra optionnel

Factory : `get_backend(cfg)` retourne le backend correspondant à `cfg.transcription.backend`.
"""

from __future__ import annotations

from .base import (
    BACKEND_REGISTRY,
    BackendInfo,
    TranscriptionBackend,
    get_backend,
    list_available_backends,
)
from .whisper import WhisperBackend  # enregistre 'whisper' au chargement

__all__ = [
    "BACKEND_REGISTRY",
    "BackendInfo",
    "TranscriptionBackend",
    "WhisperBackend",
    "get_backend",
    "list_available_backends",
]
