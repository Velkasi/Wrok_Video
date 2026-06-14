"""Façade transcription : fournit `Transcriber`, `Segment`, `TranscriptionResult`
compatible avec le code historique, mais délègue au registry de backends.

Migration : la logique faster-whisper a été déplacée dans
`core/backends/whisper.py`. Le backend NeMo Canary est dans `backends/canary.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path

from ..config import TranscriptionConfig
from .backends import get_backend
from .backends.base import Segment, TranscriptionResult

# Réexport des helpers CUDA pour rétro-compat (anciens tests/import)
from .backends.whisper import (  # noqa: F401
    _add_nvidia_dll_dirs,
    _candidate_nvidia_roots,
    _probe_cuda_libs,
    _resolve_device,
)

__all__ = [
    "Segment",
    "Transcriber",
    "TranscriptionResult",
    "_add_nvidia_dll_dirs",
    "_candidate_nvidia_roots",
    "_probe_cuda_libs",
    "_resolve_device",
]

logger = logging.getLogger(__name__)


class Transcriber:
    """Wrapper qui charge le backend approprié depuis la config et délègue."""

    def __init__(self, cfg: TranscriptionConfig):
        self.cfg = cfg
        self._backend = get_backend(cfg)
        logger.info(
            "Transcriber prêt : backend=%s model=%s",
            cfg.backend, cfg.model,
        )

    def transcribe(
        self,
        audio_path: Path | str,
        progress_cb: Callable[[float], None] | None = None,
    ) -> TranscriptionResult:
        return self._backend.transcribe(audio_path, progress_cb=progress_cb)

    def stream_segments(self, audio_path: Path | str) -> Iterator[Segment]:
        # Implémentation simple : transcribe complet puis itère
        result = self._backend.transcribe(audio_path)
        yield from result.segments
