"""Widget réutilisable : combobox de sélection backend+modèle de transcription."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from ..config import TranscriptionConfig
from ..core.backends import list_available_backends

logger = logging.getLogger(__name__)


class ModelSelector(QWidget):
    """Combobox listant tous les couples (backend, modèle) sélectionnables."""

    changed = Signal(str, str)  # (backend, model) émis quand l'utilisateur change

    def __init__(self, cfg: TranscriptionConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.combo = QComboBox()
        self._populate()
        self.combo.currentIndexChanged.connect(self._on_changed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Modèle :"))
        lay.addWidget(self.combo, 1)

    def _populate(self) -> None:
        # Modèle Qt en QStandardItemModel pour pouvoir désactiver des items
        model = QStandardItemModel(self.combo)
        self.combo.setModel(model)

        infos = list_available_backends()
        current_idx = 0
        for i, info in enumerate(infos):
            label = f"{info.label} — {info.size_mb} MB"
            if info.languages and info.languages != ["multi"]:
                label += f" ({'/'.join(info.languages)})"
            item = QStandardItem(label)
            item.setData((info.backend, info.model), Qt.ItemDataRole.UserRole)
            if not info.available:
                # Item grisé + non sélectionnable
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(
                    info.notes + "\nInstaller la dépendance pour activer ce modèle."
                )
            else:
                item.setToolTip(info.notes)
            model.appendRow(item)
            if (info.backend, info.model) == (self.cfg.backend, self.cfg.model) and info.available:
                current_idx = i
        self.combo.setCurrentIndex(current_idx)

    def _on_changed(self, _i: int) -> None:
        model = self.combo.model()
        idx = self.combo.currentIndex()
        data = model.item(idx).data(Qt.ItemDataRole.UserRole) if idx >= 0 else None
        if isinstance(data, tuple) and len(data) == 2:
            backend, model_name = data
            if (backend, model_name) != (self.cfg.backend, self.cfg.model):
                logger.info("Sélection backend changée : %s/%s", backend, model_name)
                self.cfg.backend = backend
                self.cfg.model = model_name
                self.changed.emit(backend, model_name)
