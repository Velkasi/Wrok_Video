"""Dialog de configuration : dossier de sortie, modèles Whisper/Ollama, capture."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, save_user_config


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Paramètres")
        self.setMinimumWidth(560)
        self.cfg = cfg

        # ----- Sortie ---------------------------------------------------------
        self.folder_edit = QLineEdit(str(cfg.output.folder))
        self.btn_browse = QPushButton("…")
        self.btn_browse.clicked.connect(self._pick_folder)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.btn_browse)

        out_box = QGroupBox("Dossier de sortie")
        out_form = QFormLayout()
        out_form.addRow("Dossier :", folder_row)
        out_box.setLayout(out_form)

        # ----- Whisper / Ollama / Capture ------------------------------------
        self.whisper_model = QComboBox()
        self.whisper_model.addItems(["small", "medium", "large-v3"])
        self.whisper_model.setCurrentText(cfg.whisper.model)

        self.whisper_lang = QLineEdit(cfg.whisper.language)

        self.whisper_device = QComboBox()
        self.whisper_device.addItems(["auto", "cpu", "cuda"])
        self.whisper_device.setCurrentText(cfg.whisper.device)

        self.ollama_model = QLineEdit(cfg.ollama.model)
        self.ollama_port = QSpinBox()
        self.ollama_port.setRange(1024, 65535)
        self.ollama_port.setValue(cfg.ollama.port)

        self.fps = QSpinBox()
        self.fps.setRange(1, 30)
        self.fps.setValue(cfg.recording.screen.fps)

        misc_box = QGroupBox("Modèles & capture")
        misc_form = QFormLayout()
        misc_form.addRow("Modèle Whisper :", self.whisper_model)
        misc_form.addRow("Langue Whisper :", self.whisper_lang)
        misc_form.addRow("Device Whisper :", self.whisper_device)
        misc_form.addRow("Modèle Ollama :", self.ollama_model)
        misc_form.addRow("Port Ollama :", self.ollama_port)
        misc_form.addRow("FPS capture écran :", self.fps)
        misc_box.setLayout(misc_form)

        # ----- OK / Cancel ----------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(out_box)
        root.addWidget(misc_box)
        root.addWidget(buttons)

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Dossier de sortie", self.folder_edit.text()
        )
        if path:
            self.folder_edit.setText(path)

    def accept(self) -> None:
        self.cfg.output.folder = Path(self.folder_edit.text())
        self.cfg.whisper.model = self.whisper_model.currentText()
        self.cfg.whisper.language = self.whisper_lang.text() or "fr"
        self.cfg.whisper.device = self.whisper_device.currentText()
        self.cfg.ollama.model = self.ollama_model.text()
        self.cfg.ollama.port = self.ollama_port.value()
        self.cfg.recording.screen.fps = self.fps.value()
        save_user_config(self.cfg)
        super().accept()
