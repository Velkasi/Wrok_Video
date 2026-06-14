"""QObject workers à exécuter dans un QThread (pas de UI dans le thread du modèle)."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from ..core.pipeline import Pipeline, PipelineResult
from ..core.recorder import Recorder, RecordingSession

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
class FileWorker(QObject):
    """Mode A : traite un fichier vidéo/audio existant."""

    progress = Signal(str, float)   # (étape, 0..1)
    finished = Signal(object)       # PipelineResult
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, media_path: Path, title: str | None = None):
        super().__init__()
        self.pipeline = pipeline
        self.media_path = media_path
        self.title = title

    @Slot()
    def run(self) -> None:
        try:
            result = self.pipeline.process_file(
                self.media_path,
                title=self.title,
                progress=lambda step, p: self.progress.emit(step, p),
            )
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001
            logger.exception("FileWorker a échoué")
            self.failed.emit(str(e))


# ----------------------------------------------------------------------------
class LiveWorker(QObject):
    """Mode B : pilote une session de capture, puis appelle le pipeline.

    Architecture signaux :
      - tab → start_signal → start_recording (queued, dans le thread du worker)
      - tab → stop_signal  → stop_and_process (queued, dans le thread du worker)
    Cela évite QMetaObject.invokeMethod par nom (qui exige Q_INVOKABLE/@Slot exposé
    et échoue silencieusement sinon).
    """

    # Signaux entrants (UI -> worker)
    start_signal = Signal()
    stop_signal = Signal()
    # Signaux sortants (worker -> UI)
    state = Signal(str)             # "recording" | "processing"
    progress = Signal(str, float)
    finished = Signal(object)       # PipelineResult
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, recorder: Recorder, title: str | None = None):
        super().__init__()
        self.pipeline = pipeline
        self.recorder = recorder
        self.title = title or f"Réunion {datetime.now():%Y-%m-%d %H:%M}"
        self._tmp = Path(tempfile.mkdtemp(prefix="reunion-live-"))
        # Auto-câblage : ces connexions seront résolues en queued une fois moveToThread fait
        self.start_signal.connect(self.start_recording)
        self.stop_signal.connect(self.stop_and_process)

    @Slot()
    def start_recording(self) -> None:
        try:
            self.state.emit("recording")
            self.recorder.start(self._tmp)
            logger.info("Recording démarré dans %s", self._tmp)
        except Exception as e:  # noqa: BLE001
            logger.exception("start_recording a échoué")
            self.failed.emit(f"Démarrage capture : {e}")

    @Slot()
    def stop_and_process(self) -> None:
        try:
            logger.info("Arrêt de la capture demandé")
            session: RecordingSession = self.recorder.stop()
            logger.info(
                "Session : mic=%s sys=%s screen=%s mixed=%s final=%s",
                session.mic_wav, session.system_wav, session.screen_mp4,
                session.mixed_audio, session.final_mp4,
            )
            self.state.emit("processing")

            # Choix du média à transcrire — fallback en cascade si le mux a échoué
            target = (
                session.final_mp4 if session.final_mp4 and session.final_mp4.exists() else
                session.mixed_audio if session.mixed_audio and session.mixed_audio.exists() else
                session.mic_wav if session.mic_wav and session.mic_wav.exists() else
                session.system_wav if session.system_wav and session.system_wav.exists() else
                None
            )
            if target is None:
                raise RuntimeError(
                    f"Aucun fichier produit dans {session.work_dir}. "
                    "Vérifie ffmpeg.exe + permissions micro/audio."
                )
            logger.info("Transcription cible : %s", target)

            # Pour le frontmatter Obsidian (lien vidéo) : préférer le MP4 final
            video_for_md = session.final_mp4 if (
                session.final_mp4 and session.final_mp4.exists()
            ) else None

            result: PipelineResult = self.pipeline.process_recording(
                target,
                title=self.title,
                progress=lambda step, p: self.progress.emit(step, p),
                video_path=video_for_md,
            )
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001
            logger.exception("stop_and_process a échoué")
            self.failed.emit(str(e))
