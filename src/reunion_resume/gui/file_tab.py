"""Onglet 'Fichier' : sélectionner un média, lancer transcription + résumé."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.pipeline import Pipeline
from .model_selector import ModelSelector
from .workers import FileWorker

MEDIA_FILTER = "Médias (*.mp4 *.mkv *.mov *.avi *.webm *.mp3 *.wav *.m4a *.flac);;Tous (*)"
MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac",
}


class FileTab(QWidget):
    def __init__(self, pipeline: Pipeline, parent: QWidget | None = None):
        super().__init__(parent)
        self.pipeline = pipeline
        self._thread: QThread | None = None
        self._worker: FileWorker | None = None
        self._queue: list[Path] = []
        self.setAcceptDrops(True)
        self.model_selector = ModelSelector(pipeline.cfg.transcription)

        # Widgets
        self.drop_hint = QLabel("⤓  Glisse-dépose des fichiers vidéo/audio ici")
        self.drop_hint.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; padding: 18px; "
            "color: #666; font-size: 11pt; }"
        )
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("…ou sélectionne un fichier")
        self.browse_btn = QPushButton("Parcourir…")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Titre (optionnel — défaut : nom de fichier)")
        self.run_btn = QPushButton("Transcrire et résumer")
        self.run_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.status_label = QLabel("Prêt.")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.open_btn = QPushButton("Ouvrir le résumé généré")
        self.open_btn.setEnabled(False)
        self._last_md: Path | None = None

        # Layout
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.drop_hint)
        root.addWidget(QLabel("Fichier :"))
        root.addLayout(path_row)
        root.addWidget(QLabel("Titre :"))
        root.addWidget(self.title_edit)
        root.addWidget(self.model_selector)
        root.addWidget(self.run_btn)
        root.addWidget(self.progress)
        root.addWidget(self.status_label)
        root.addWidget(QLabel("Journal :"))
        root.addWidget(self.log, 1)
        root.addWidget(self.open_btn)

        # Signals
        self.browse_btn.clicked.connect(self._browse)
        self.path_edit.textChanged.connect(self._on_path_changed)
        self.run_btn.clicked.connect(self._run)
        self.open_btn.clicked.connect(self._open_result)

    # ------------------------------------------------------------------ drag & drop
    def _has_media_urls(self, event: QDragEnterEvent | QDropEvent) -> bool:
        md = event.mimeData()
        if not md.hasUrls():
            return False
        for url in md.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in MEDIA_EXTENSIONS:
                    return True
        return False

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if self._has_media_urls(event):
            event.acceptProposedAction()
            self.drop_hint.setStyleSheet(
                "QLabel { border: 2px dashed #2a82da; border-radius: 8px; padding: 18px; "
                "color: #2a82da; background: #eaf3fb; font-size: 11pt; }"
            )
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override,no-untyped-def]
        self._reset_drop_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        self._reset_drop_style()
        if not self._has_media_urls(event):
            event.ignore()
            return
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in MEDIA_EXTENSIONS and p.exists():
                    paths.append(p)
        event.acceptProposedAction()
        self._enqueue_and_run(paths)

    def _reset_drop_style(self) -> None:
        self.drop_hint.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; padding: 18px; "
            "color: #666; font-size: 11pt; }"
        )

    def _enqueue_and_run(self, paths: list[Path]) -> None:
        """Empile les fichiers et démarre le traitement s'il n'y en a pas en cours."""
        if not paths:
            return
        self._queue.extend(paths)
        self.log.append(f"+ {len(paths)} fichier(s) en file (total : {len(self._queue)})")
        if self._thread is None:
            self._run_next()

    def _run_next(self) -> None:
        if not self._queue:
            self.status_label.setText("File vide.")
            return
        media = self._queue.pop(0)
        self.path_edit.setText(str(media))
        self._start_pipeline(media, self.title_edit.text().strip() or None)

    # ------------------------------------------------------------------ slots
    def _browse(self) -> None:
        # Repli sur un dossier "léger" (jamais le cwd qui peut être le dossier
        # dist 11 GB avec des milliers de DLLs → freeze du dialogue natif).
        home = Path.home()
        initial = next(
            (str(p) for p in (home / "Videos", home / "Vidéos",
                              home / "Documents", home) if p.exists()),
            str(home),
        )
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un média", initial, MEDIA_FILTER)
        if path:
            self.path_edit.setText(path)

    def _on_path_changed(self, text: str) -> None:
        self.run_btn.setEnabled(bool(text) and Path(text).exists())

    def _run(self) -> None:
        media = Path(self.path_edit.text())
        if not media.exists():
            self.status_label.setText("Fichier introuvable.")
            return
        self._start_pipeline(media, self.title_edit.text().strip() or None)

    def _start_pipeline(self, media: Path, title: str | None) -> None:
        self.run_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText(f"Traitement : {media.name}")
        self.log.append(f"\n> {media.name}")

        self._thread = QThread(self)
        self._worker = FileWorker(self.pipeline, media, title)
        self._worker.moveToThread(self._thread)
        # run() est decore @Slot — connexion via started fonctionne en queued
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_progress(self, step: str, p: float) -> None:
        self.progress.setValue(int(p * 1000))
        self.status_label.setText(step)
        self.log.append(f"[{p*100:5.1f}%] {step}")

    def _on_finished(self, result) -> None:  # type: ignore[no-untyped-def]
        self._last_md = result.output_md
        self.status_label.setText(f"Terminé : {result.output_md.name}")
        self.log.append(f"\n✓ Résumé écrit : {result.output_md}")
        self.run_btn.setEnabled(True)
        self.open_btn.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        self.status_label.setText("Échec.")
        self.log.append(f"\n✗ Erreur : {msg}")
        self.run_btn.setEnabled(True)

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        # Enchaîne la file si d'autres fichiers ont été déposés pendant le traitement
        if self._queue:
            self._run_next()

    def _open_result(self) -> None:
        if self._last_md and self._last_md.exists():
            os.startfile(self._last_md)  # type: ignore[attr-defined]  # Windows-only
