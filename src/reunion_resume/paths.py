"""Résolution de chemins compatible dev local et build PyInstaller (onedir/onefile)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True si l'app tourne depuis un build PyInstaller."""
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """Racine de l'application.

    - En dev : racine du repo (parent de src/)
    - En frozen onedir : dossier contenant le .exe
    - En frozen onefile : dossier d'extraction temporaire (sys._MEIPASS)
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent
    # dev : ce fichier est src/reunion_resume/paths.py → remonter 3 niveaux
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """Chemin vers une ressource embarquée (binaires, modèles, configs).

    Cherche d'abord dans <app_root>/resources/, fallback <_MEIPASS>/resources/.
    """
    base = app_root() / "resources"
    candidate = base.joinpath(*parts)
    if candidate.exists():
        return candidate
    # Fallback : certains spec PyInstaller copient à la racine
    alt = app_root().joinpath(*parts)
    return alt if alt.exists() else candidate


def user_config_dir() -> Path:
    """Dossier APPDATA pour la config utilisateur (Windows)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "reunion-resume"
    return Path.home() / ".reunion-resume"


def user_data_dir() -> Path:
    """Dossier de données runtime (logs, cache temp, modèles téléchargés post-install)."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "reunion-resume"
    return Path.home() / ".reunion-resume" / "data"


def ffmpeg_exe() -> Path:
    """Chemin du binaire ffmpeg embarqué."""
    return resource_path("ffmpeg", "ffmpeg.exe")


def ollama_exe() -> Path:
    """Chemin du binaire ollama embarqué."""
    return resource_path("ollama", "ollama.exe")


def whisper_model_dir() -> Path:
    """Dossier du modèle Whisper CT2 embarqué (par défaut : medium)."""
    return resource_path("models", "whisper-medium-ct2")


def ollama_models_dir() -> Path:
    """Dossier OLLAMA_MODELS pointant sur les blobs embarqués."""
    return resource_path("models", "ollama")
