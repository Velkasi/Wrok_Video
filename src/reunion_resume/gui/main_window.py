"""Fenêtre principale : 2 onglets (Fichier / Live) + menu Paramètres."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget, QWidget

from .. import __version__
from ..config import AppConfig
from ..core.pipeline import Pipeline
from .file_tab import MEDIA_EXTENSIONS, FileTab
from .live_tab import LiveTab
from .settings_dlg import SettingsDialog

logger = logging.getLogger(__name__)


def _bypass_uipi_dnd(hwnd: int) -> None:
    """Autorise les messages drag-drop venant de processus de niveau d'intégrité différent.

    Sans ça, drag depuis l'Explorer Windows vers une app frozen non signée
    est silencieusement filtré par UIPI (Windows 7+). Pas d'erreur, juste rien.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        WM_COPYGLOBALDATA = 0x0049
        WM_COPYDATA = 0x004A
        WM_DROPFILES = 0x0233
        MSGFLT_ALLOW = 1
        user32 = ctypes.windll.user32
        for msg in (WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA):
            user32.ChangeWindowMessageFilterEx(hwnd, msg, MSGFLT_ALLOW, None)
    except Exception:  # noqa: BLE001
        logger.exception("Echec bypass UIPI drag-drop (non bloquant)")


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig, pipeline: Pipeline, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.pipeline = pipeline
        self.setWindowTitle(f"Wrok-video v{__version__}")
        self.resize(900, 700)
        self.setAcceptDrops(True)  # drop sur toute la fenêtre

        self.tabs = QTabWidget()
        self.tabs.setAcceptDrops(True)  # essentiel : sans ça, QTabWidget intercepte
        self.file_tab = FileTab(pipeline)
        self.live_tab = LiveTab(cfg, pipeline)
        self.tabs.addTab(self.file_tab, "Fichier")
        self.tabs.addTab(self.live_tab, "Live")
        self.setCentralWidget(self.tabs)

        # Menu
        menu_file = self.menuBar().addMenu("&Fichier")
        act_settings = QAction("&Paramètres…", self)
        act_settings.triggered.connect(self._open_settings)
        menu_file.addAction(act_settings)
        menu_file.addSeparator()
        act_quit = QAction("&Quitter", self)
        act_quit.triggered.connect(self.close)
        menu_file.addAction(act_quit)

        menu_help = self.menuBar().addMenu("&Aide")
        act_about = QAction("À propos", self)
        act_about.triggered.connect(self._about)
        menu_help.addAction(act_about)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            QMessageBox.information(
                self,
                "Paramètres",
                "Paramètres enregistrés. Redémarre l'application pour prendre en compte "
                "les changements de modèle Whisper.",
            )

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "À propos",
            f"<h3>Wrok-video v{__version__}</h3>"
            "<p>Outil local de transcription/résumé via Whisper + Ollama.</p>"
            "<p>Sortie vers vault Obsidian.</p>",
        )

    # ------------------------------------------------------------------ DnD global
    def _collect_media_paths(self, event: QDragEnterEvent | QDropEvent) -> list[Path]:
        out: list[Path] = []
        md = event.mimeData()
        if not md.hasUrls():
            return out
        for url in md.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.suffix.lower() in MEDIA_EXTENSIONS and p.exists():
                    out.append(p)
        return out

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if self._collect_media_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        paths = self._collect_media_paths(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        # Bascule sur l'onglet Fichier et empile
        self.tabs.setCurrentWidget(self.file_tab)
        self.file_tab._enqueue_and_run(paths)

    def showEvent(self, event) -> None:  # type: ignore[override,no-untyped-def]
        super().showEvent(event)
        # Le HWND n'existe qu'après show() — appliquer le fix UIPI ici
        if not getattr(self, "_uipi_applied", False):
            _bypass_uipi_dnd(int(self.winId()))
            self._uipi_applied = True

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.pipeline.shutdown()
        super().closeEvent(event)
