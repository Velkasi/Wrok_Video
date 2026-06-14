"""Pipeline haut niveau : orchestration transcription + résumé + écriture Obsidian.

Utilisé par la GUI (workers) et la CLI. Les composants lourds (Transcriber, Ollama)
sont initialisés une seule fois et réutilisés.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from . import mixer
from .obsidian import ObsidianWriter
from .ollama_runtime import OllamaRuntime
from .summarizer import Summarizer, SummaryResult
from .transcriber import Transcriber, TranscriptionResult

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]  # (étape, 0..1)


@dataclass
class PipelineResult:
    output_md: Path
    transcription: TranscriptionResult
    summary: SummaryResult


class Pipeline:
    """Composants partagés entre invocations."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.ollama = OllamaRuntime(cfg.ollama)
        self._transcriber: Transcriber | None = None
        self._summarizer: Summarizer | None = None
        self._writer = ObsidianWriter(cfg.output)

    # ------------------------------------------------------------------ lazy
    def _ensure_loaded(self) -> None:
        # Le backend de transcription peut changer entre deux appels (sélecteur GUI)
        # → recharger si backend/model a changé
        cur = (self.cfg.transcription.backend, self.cfg.transcription.model)
        prev = getattr(self, "_last_backend_key", None)
        if self._transcriber is None or cur != prev:
            self._transcriber = Transcriber(self.cfg.transcription)
            self._last_backend_key = cur

        if self._summarizer is None:
            self.ollama.start()
            self._summarizer = Summarizer(self.cfg.ollama, self.cfg.prompts)
            self.ollama.log_runtime_info()

    # ------------------------------------------------------------------ API
    def process_file(
        self,
        media_path: Path,
        title: str | None = None,
        progress: ProgressFn | None = None,
    ) -> PipelineResult:
        """Traite un fichier média (audio ou vidéo) → résumé Markdown."""
        self._ensure_loaded()
        assert self._transcriber and self._summarizer

        media_path = Path(media_path)
        if not media_path.exists():
            raise FileNotFoundError(media_path)
        title = title or media_path.stem

        if progress:
            progress("Extraction audio", 0.05)

        with tempfile.TemporaryDirectory(prefix="reunion-") as tmp:
            wav = Path(tmp) / "audio.wav"
            mixer.extract_audio(media_path, wav, samplerate=16000)

            if progress:
                progress("Transcription", 0.1)

            def _trans_progress(p: float) -> None:
                if progress:
                    progress("Transcription", 0.1 + 0.6 * p)

            transcription = self._transcriber.transcribe(wav, progress_cb=_trans_progress)

        if progress:
            progress("Résumé", 0.75)
        summary = self._summarizer.summarize(transcription.full_text)

        if progress:
            progress("Écriture Obsidian", 0.95)
        out_md = self._writer.write_summary(
            title=title,
            transcription=transcription,
            summary=summary,
            source="file",
            source_path=media_path,
        )
        if progress:
            progress("Terminé", 1.0)
        return PipelineResult(output_md=out_md, transcription=transcription, summary=summary)

    def process_recording(
        self,
        media_path: Path,
        title: str | None = None,
        progress: ProgressFn | None = None,
        video_path: Path | None = None,
    ) -> PipelineResult:
        """Mode live : `media_path` peut être un MP4 (idéal) OU un WAV de fallback.

        `video_path` : chemin de la vidéo à lier dans le frontmatter Obsidian
        (None si seul l'audio a été produit).
        """
        self._ensure_loaded()
        assert self._transcriber and self._summarizer

        media_path = Path(media_path)
        title = title or f"Réunion {media_path.stem}"

        with tempfile.TemporaryDirectory(prefix="reunion-") as tmp:
            wav = Path(tmp) / "audio.wav"
            # Si on a déjà du WAV, on le passe direct ; sinon ffmpeg extrait
            if media_path.suffix.lower() == ".wav":
                wav = media_path
            else:
                mixer.extract_audio(media_path, wav, samplerate=16000)

            if progress:
                progress("Transcription", 0.1)

            def _trans_progress(p: float) -> None:
                if progress:
                    progress("Transcription", 0.1 + 0.6 * p)

            transcription = self._transcriber.transcribe(wav, progress_cb=_trans_progress)

        if progress:
            progress("Résumé", 0.75)
        summary = self._summarizer.summarize(transcription.full_text)

        if progress:
            progress("Écriture Obsidian", 0.95)
        out_md = self._writer.write_summary(
            title=title,
            transcription=transcription,
            summary=summary,
            source="live",
            video_path=video_path,
        )
        if progress:
            progress("Terminé", 1.0)
        return PipelineResult(output_md=out_md, transcription=transcription, summary=summary)

    def shutdown(self) -> None:
        self.ollama.stop()
