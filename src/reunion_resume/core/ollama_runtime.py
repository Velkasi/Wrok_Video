"""Cycle de vie du serveur Ollama embarqué.

Lance `ollama.exe serve` en sous-processus, configure OLLAMA_MODELS pour pointer
sur les blobs embarqués, attend que l'API soit prête, puis fournit un client.

Tue les éventuels Ollama zombies au démarrage (résidus de runs précédents) qui
squattent la VRAM et empêcheraient le GPU offload.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from ..config import OllamaConfig
from ..paths import ollama_exe, ollama_models_dir

logger = logging.getLogger(__name__)


# Empêche fenêtres console quand spawn depuis exe windowed
_NO_WINDOW_KW: dict = {}
if os.name == "nt":
    _NO_WINDOW_KW["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
    _NO_WINDOW_KW["startupinfo"] = _si


def _kill_stale_ollama() -> int:
    """Tue tous les processus ollama.exe résiduels (Windows). Retourne le nombre tué."""
    if os.name != "nt":
        return 0
    try:
        proc = subprocess.run(
            ["taskkill", "/F", "/IM", "ollama.exe"],
            capture_output=True, text=True, **_NO_WINDOW_KW,
        )
        if proc.returncode == 0:
            # taskkill rapporte "SUCCESS" pour chaque PID tué
            killed = proc.stdout.count("SUCCESS")
            if killed:
                logger.info("Ollama zombies tués : %d", killed)
            return killed
        return 0
    except (FileNotFoundError, OSError):
        return 0


class OllamaRuntime:
    """Gestionnaire du processus serveur ollama."""

    def __init__(self, cfg: OllamaConfig):
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._started = False

    def is_alive(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"{self.cfg.base_url}/api/tags", timeout=1
            ) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def start(self) -> None:
        """Démarre le serveur ollama. Tue tout zombie d'abord pour libérer la VRAM."""
        # Si un Ollama répond déjà, le considérer comme "à nous" sauf si c'est un zombie.
        # Pour être certain de partir propre (VRAM libre), on tue tout puis on relance.
        if self.is_alive():
            logger.warning(
                "Ollama déjà actif sur %s — kill préventif pour libérer la VRAM",
                self.cfg.base_url,
            )
            _kill_stale_ollama()
            time.sleep(1.0)
        else:
            # Aucun serveur détecté : tuer quand même les zombies orphelins (sans port)
            _kill_stale_ollama()

        exe = ollama_exe()
        if not exe.exists():
            raise FileNotFoundError(
                f"Binaire ollama introuvable : {exe}. "
                "Lancer scripts/download_models.py pour le récupérer."
            )

        env = os.environ.copy()
        models_dir = ollama_models_dir()
        if models_dir.exists():
            env["OLLAMA_MODELS"] = str(models_dir)
            logger.info("OLLAMA_MODELS = %s", models_dir)
        env["OLLAMA_HOST"] = f"{self.cfg.host}:{self.cfg.port}"

        logger.info("Démarrage de ollama serve...")
        t0 = time.monotonic()
        self._proc = subprocess.Popen(
            [str(exe), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_NO_WINDOW_KW,
        )
        self._started = True
        atexit.register(self.stop)

        # Health-check
        deadline = t0 + self.cfg.startup_timeout
        while time.monotonic() < deadline:
            if self.is_alive():
                logger.info("Ollama prêt après %.1fs", time.monotonic() - t0)
                return
            time.sleep(0.5)
        self.stop()
        raise TimeoutError(
            f"Ollama n'a pas démarré dans les {self.cfg.startup_timeout}s impartis."
        )

    def log_runtime_info(self) -> None:
        """Logge des infos utiles : version, modèles déjà chargés, GPU/CPU split.

        Appeler APRÈS un `summarizer.summarize()` pour voir où le modèle tourne.
        """
        try:
            with urllib.request.urlopen(f"{self.cfg.base_url}/api/version", timeout=2) as r:
                v = json.loads(r.read())
                logger.info("Ollama version : %s", v.get("version", "?"))
        except Exception:  # noqa: BLE001
            pass
        try:
            with urllib.request.urlopen(f"{self.cfg.base_url}/api/ps", timeout=2) as r:
                data = json.loads(r.read())
            for m in data.get("models", []):
                total = m.get("size", 0)
                vram = m.get("size_vram", 0)
                pct = round(100 * vram / max(total, 1))
                logger.info(
                    "Modèle %s : %.2f GB total, %.2f GB GPU (%d%%), %.2f GB CPU",
                    m.get("name", "?"),
                    total / 1024**3, vram / 1024**3, pct,
                    (total - vram) / 1024**3,
                )
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            logger.info("Arrêt de ollama serve")
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            except Exception as e:  # noqa: BLE001
                logger.warning("Erreur arrêt ollama : %s", e)
        self._proc = None
        self._started = False

    def __enter__(self) -> OllamaRuntime:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
