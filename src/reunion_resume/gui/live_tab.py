"""Onglet 'Live' : capture mic + audio système + écran, puis transcription/résumé."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from ..core.pipeline import Pipeline
from ..core.recorder import Recorder, list_monitors
from .model_selector import ModelSelector
from .workers import LiveWorker


class LiveTab(QWidget):
    def __init__(self, cfg: AppConfig, pipeline: Pipeline, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.pipeline = pipeline
        self._thread: QThread | None = None
        self._worker: LiveWorker | None = None
        self._recorder: Recorder | None = None
        self._timer: QTimer | None = None
        self._t_start: datetime | None = None

        # Sélection sources
        self.cb_mic = QCheckBox("Micro")
        self.cb_mic.setChecked(cfg.recording.mic.enabled)
        self.cb_sys = QCheckBox("Audio système (loopback)")
        self.cb_sys.setChecked(cfg.recording.system_audio.enabled)
        self.cb_screen = QCheckBox("Capture écran")
        self.cb_screen.setChecked(cfg.recording.screen.enabled)

        # Sélection écran (multi-moniteurs)
        self.monitor_combo = QComboBox()
        self._populate_monitors()
        self.cb_screen.toggled.connect(self.monitor_combo.setEnabled)
        self.monitor_combo.setEnabled(self.cb_screen.isChecked())

        # Sélecteur de modèle de transcription
        self.model_selector = ModelSelector(cfg.transcription)

        # Titre
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Titre de la réunion (optionnel)")

        # Contrôles
        self.start_btn = QPushButton("● Démarrer la capture")
        self.stop_btn = QPushButton("■ Arrêter et résumer")
        self.stop_btn.setEnabled(False)
        self.timer_label = QLabel("00:00:00")
        self.timer_label.setStyleSheet("font-size: 18pt; font-family: Consolas, monospace;")

        # Status / progression du post-traitement
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.status_label = QLabel("Prêt.")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.open_btn = QPushButton("Ouvrir le résumé généré")
        self.open_btn.setEnabled(False)
        self._last_md: Path | None = None

        # Layout
        sources = QHBoxLayout()
        sources.addWidget(self.cb_mic)
        sources.addWidget(self.cb_sys)
        sources.addWidget(self.cb_screen)
        sources.addStretch()

        screen_row = QHBoxLayout()
        screen_row.addWidget(QLabel("Écran à capturer :"))
        screen_row.addWidget(self.monitor_combo, 1)
        screen_row.addWidget(QPushButton("↻", clicked=self._refresh_monitors,
                                          toolTip="Rafraîchir la liste des écrans"))

        controls = QHBoxLayout()
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch()
        controls.addWidget(self.timer_label)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Sources :"))
        root.addLayout(sources)
        root.addLayout(screen_row)
        root.addWidget(self.model_selector)
        root.addWidget(QLabel("Titre :"))
        root.addWidget(self.title_edit)
        root.addLayout(controls)
        root.addWidget(self.progress)
        root.addWidget(self.status_label)
        root.addWidget(QLabel("Journal :"))
        root.addWidget(self.log, 1)
        root.addWidget(self.open_btn)

        # Signals
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.open_btn.clicked.connect(self._open_result)

    # ------------------------------------------------------------------ écrans
    def _populate_monitors(self) -> None:
        self.monitor_combo.clear()
        monitors = list_monitors()
        if not monitors:
            self.monitor_combo.addItem("(aucun écran détecté)", -1)
            return
        for m in monitors:
            self.monitor_combo.addItem(m.label, m.index)
        # Resélectionne l'écran courant de la config si encore valide
        wanted = self.cfg.recording.screen.monitor
        for i in range(self.monitor_combo.count()):
            if self.monitor_combo.itemData(i) == wanted:
                self.monitor_combo.setCurrentIndex(i)
                return
        # Sinon défaut sur le premier écran physique (index 1)
        for i in range(self.monitor_combo.count()):
            if self.monitor_combo.itemData(i) == 1:
                self.monitor_combo.setCurrentIndex(i)
                return

    def _refresh_monitors(self) -> None:
        self._populate_monitors()
        self.log.append("Liste des écrans rafraîchie.")

    # ------------------------------------------------------------------ slots
    def _on_start(self) -> None:
        # Synchronise checkboxes + écran → cfg.recording (copie locale)
        self.cfg.recording.mic.enabled = self.cb_mic.isChecked()
        self.cfg.recording.system_audio.enabled = self.cb_sys.isChecked()
        self.cfg.recording.screen.enabled = self.cb_screen.isChecked()
        sel = self.monitor_combo.currentData()
        if isinstance(sel, int) and sel >= 0:
            self.cfg.recording.screen.monitor = sel
        if not (self.cb_mic.isChecked() or self.cb_sys.isChecked()):
            self.status_label.setText("Sélectionner au moins une source audio.")
            return

        self._recorder = Recorder(self.cfg.recording)
        title = self.title_edit.text().strip() or None
        self._worker = LiveWorker(self.pipeline, self._recorder, title)

        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        # Signaux UI ← worker
        self._worker.state.connect(self._on_state)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

        # Démarrer la capture via signal (évite QMetaObject.invokeMethod par nom)
        self._worker.start_signal.emit()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.log.clear()
        self.progress.setValue(0)
        self._t_start = datetime.now()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)

    def _on_stop(self) -> None:
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Arrêt de la capture, traitement en cours…")
        if self._timer:
            self._timer.stop()
        if self._worker:
            # Signal queued → exécuté dans le thread du worker, sans bloquer l'UI
            self._worker.stop_signal.emit()

    def _tick(self) -> None:
        if self._t_start:
            d = datetime.now() - self._t_start
            total = int(d.total_seconds())
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def _on_state(self, st: str) -> None:
        self.status_label.setText({"recording": "Enregistrement…", "processing": "Traitement…"}[st])
        self.log.append(f"État : {st}")

    def _on_progress(self, step: str, p: float) -> None:
        self.progress.setValue(int(p * 1000))
        self.status_label.setText(step)
        self.log.append(f"[{p*100:5.1f}%] {step}")

    def _on_finished(self, result) -> None:  # type: ignore[no-untyped-def]
        self._last_md = result.output_md
        self.status_label.setText(f"Terminé : {result.output_md.name}")
        self.log.append(f"\n✓ Résumé écrit : {result.output_md}")
        self.start_btn.setEnabled(True)
        self.open_btn.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        self.status_label.setText("Échec.")
        self.log.append(f"\n✗ Erreur : {msg}")
        self.start_btn.setEnabled(True)

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._recorder = None
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _open_result(self) -> None:
        if self._last_md and self._last_md.exists():
            os.startfile(self._last_md)  # type: ignore[attr-defined]
