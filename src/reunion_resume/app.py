"""Bootstrap de l'application GUI."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from PySide6.QtWidgets import QApplication

from .config import load_config
from .core.pipeline import Pipeline
from .gui.main_window import MainWindow
from .paths import user_data_dir


def setup_logging() -> None:
    """Logs : stderr (visible si console=True ou via redirection) + fichier rotatif."""
    log_dir = user_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "wrok-video.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Eviter d'empiler les handlers entre run_gui() multiples
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    logging.getLogger(__name__).info("Logs écrits dans %s", log_file)


def _set_app_user_model_id() -> None:
    """Identifie l'app à Windows (taskbar grouping). Doit être appelée APRES QApplication
    pour ne pas casser l'init COM/OLE de Qt (sinon : OleInitialize() failed RPC_E_CHANGED_MODE).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "wrok.video.app.0.1.0"
        )
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Echec SetCurrentProcessExplicitAppUserModelID")


def run_gui() -> int:
    setup_logging()
    log = logging.getLogger(__name__)
    log.debug("run_gui: load_config")
    cfg = load_config()
    log.debug("run_gui: Pipeline.__init__")
    pipeline = Pipeline(cfg)

    # IMPORTANT : QApplication AVANT toute API shell32/COM, sinon Qt échoue à init OLE
    log.debug("run_gui: QApplication")
    qt_app = QApplication.instance() or QApplication(sys.argv)
    _set_app_user_model_id()

    log.debug("run_gui: MainWindow")
    win = MainWindow(cfg, pipeline)
    win.show()
    log.info("GUI démarrée")
    rc = qt_app.exec()
    pipeline.shutdown()
    return rc
