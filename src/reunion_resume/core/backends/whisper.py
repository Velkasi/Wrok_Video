"""Backend Whisper via faster-whisper (CTranslate2). Multilingue, GPU auto-détecté."""

from __future__ import annotations

import ctypes
import logging
import os
import site
import sys
from collections.abc import Callable
from pathlib import Path

from faster_whisper import WhisperModel

from ...config import TranscriptionConfig
from ...paths import resource_path
from .base import BackendInfo, Segment, TranscriptionResult, register_backend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CUDA detection (identique au code historique de transcriber.py)
# ---------------------------------------------------------------------------

def _candidate_nvidia_roots() -> list[Path]:
    candidates: list[Path] = []
    sp_dirs = list(site.getsitepackages())
    user_sp = site.getusersitepackages()
    if user_sp:
        sp_dirs.append(user_sp)
    for sp in sp_dirs:
        candidates.append(Path(sp) / "nvidia")
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "nvidia")
        candidates.append(Path(sys.executable).parent / "nvidia")
    # Dédoublonne sur la forme résolue (évite que le mode frozen mette deux fois
    # le même dossier nvidia/* sous _MEIPASS ET site-packages)
    seen: set[Path] = set()
    out: list[Path] = []
    for r in candidates:
        if not r.is_dir():
            continue
        rr = r.resolve()
        if rr in seen:
            continue
        seen.add(rr)
        out.append(rr)
    return out


def _add_nvidia_dll_dirs() -> list[Path]:
    if sys.platform != "win32":
        return []
    bins: list[Path] = []
    for nvidia_root in _candidate_nvidia_roots():
        for lib_dir in nvidia_root.iterdir():
            bin_dir = lib_dir / "bin"
            if bin_dir.is_dir():
                bins.append(bin_dir.resolve())

    # En mode frozen, PyInstaller met les DLLs CUDA detectees AUTO directement
    # a la racine de _internal/ (pas sous nvidia/). Ajouter aussi ce dossier.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass).resolve()
        if root not in {b.resolve() for b in bins}:
            bins.append(root)
    # Et le dossier exe (mode onedir, _internal a cote)
    if sys.platform == "win32" and not meipass:
        exe_internal = Path(sys.executable).parent / "_internal"
        if exe_internal.is_dir() and exe_internal.resolve() not in {b.resolve() for b in bins}:
            bins.append(exe_internal.resolve())
    added: list[Path] = []
    if hasattr(os, "add_dll_directory"):
        for bd in bins:
            try:
                os.add_dll_directory(str(bd))
                added.append(bd)
            except (FileNotFoundError, OSError):
                pass
    if bins:
        existing = os.environ.get("PATH", "")
        prefix = ";".join(str(b) for b in bins)
        if prefix not in existing:
            os.environ["PATH"] = prefix + ";" + existing
        logger.info(
            "DLLs nvidia ajoutées (%d dossiers) : %s",
            len(bins), [str(b.parent.name) for b in bins],
        )
    return added


def _probe_cuda_libs() -> bool:
    if sys.platform != "win32":
        return False
    _add_nvidia_dll_dirs()
    required = {
        "cublas":  ["cublas64_12.dll", "cublas64_11.dll"],
        "cudnn":   ["cudnn_ops64_9.dll", "cudnn_ops_infer64_8.dll", "cudnn64_8.dll"],
        "cudart":  ["cudart64_12.dll", "cudart64_120.dll", "cudart64_11.dll"],
    }
    missing: list[str] = []
    for key, candidates in required.items():
        ok = False
        for name in candidates:
            try:
                ctypes.CDLL(name)
                ok = True
                break
            except OSError:
                continue
        if not ok:
            missing.append(key)
    if not missing:
        logger.info("CUDA disponible : cublas + cudnn + cudart chargeables")
        return True
    logger.warning(
        "CUDA indisponible (manque : %s) → Whisper en CPU",
        ", ".join(missing),
    )
    return False


def _resolve_device(preferred: str) -> str:
    p = (preferred or "auto").lower()
    if p == "cpu":
        return "cpu"
    if p == "cuda":
        return "cuda" if _probe_cuda_libs() else "cpu"
    return "cuda" if _probe_cuda_libs() else "cpu"


# ---------------------------------------------------------------------------
# Modèles supportés (utilisé par GUI + DL)
# ---------------------------------------------------------------------------

WHISPER_MODELS: dict[str, dict] = {
    "small":            {"hf": "Systran/faster-whisper-small",            "size_mb": 500,  "label": "Whisper small (rapide CPU)"},
    "medium":           {"hf": "Systran/faster-whisper-medium",           "size_mb": 1500, "label": "Whisper medium (équilibre, défaut)"},
    "large-v3":         {"hf": "Systran/faster-whisper-large-v3",         "size_mb": 3000, "label": "Whisper large-v3 (top qualité)"},
    "large-v3-turbo":   {"hf": "Systran/faster-whisper-large-v3-turbo",   "size_mb": 1600, "label": "Whisper large-v3-turbo (8× plus rapide que large)"},
}


def _resolve_model_path(model_name: str) -> str:
    embedded = resource_path("models", f"whisper-{model_name}-ct2")
    if embedded.exists() and embedded.is_dir():
        return str(embedded)
    info = WHISPER_MODELS.get(model_name)
    if info:
        logger.warning(
            "Modèle Whisper %s non embarqué (%s), DL HuggingFace : %s",
            model_name, embedded, info["hf"],
        )
        return info["hf"]
    logger.warning("Modèle Whisper inconnu %s, tente comme identifiant HF", model_name)
    return model_name


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

@register_backend
class WhisperBackend:
    """Backend faster-whisper. Supporte small/medium/large-v3/large-v3-turbo."""

    def __init__(self, cfg: TranscriptionConfig):
        self.cfg = cfg
        model_path = _resolve_model_path(cfg.model)

        device = _resolve_device(cfg.device)
        compute_type = cfg.compute_type
        if compute_type in ("", "auto"):
            compute_type = "int8" if device == "cpu" else "float16"

        try:
            self._model = WhisperModel(model_path, device=device, compute_type=compute_type)
        except Exception as e:
            if device == "cuda":
                logger.warning("Init CUDA a échoué (%s) → fallback CPU/int8", e)
                device, compute_type = "cpu", "int8"
                self._model = WhisperModel(model_path, device=device, compute_type=compute_type)
            else:
                raise
        logger.info(
            "WhisperBackend chargé : model=%s device=%s compute_type=%s",
            cfg.model, device, compute_type,
        )

    @classmethod
    def name(cls) -> str:
        return "whisper"

    @classmethod
    def available_models(cls) -> list[BackendInfo]:
        out = []
        for variant, info in WHISPER_MODELS.items():
            embedded = resource_path("models", f"whisper-{variant}-ct2")
            available = embedded.exists() and embedded.is_dir()
            out.append(BackendInfo(
                backend="whisper",
                model=variant,
                label=info["label"] + ("" if available else "  [à télécharger]"),
                size_mb=info["size_mb"],
                languages=["multi"],
                requires_gpu=False,
                available=True,  # Whisper toujours utilisable (DL à la volée si absent)
                notes="multilingue (FR, EN, +99 langues)",
            ))
        return out

    def transcribe(
        self,
        audio_path: Path | str,
        progress_cb: Callable[[float], None] | None = None,
    ) -> TranscriptionResult:
        audio_path = Path(audio_path)
        segments_iter, info = self._model.transcribe(
            str(audio_path),
            language=self.cfg.language,
            beam_size=self.cfg.beam_size,
            vad_filter=self.cfg.vad_filter,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        duration = float(info.duration or 0.0)
        out: list[Segment] = []
        for seg in segments_iter:
            out.append(Segment(start=seg.start, end=seg.end, text=seg.text))
            if progress_cb and duration > 0:
                progress_cb(min(1.0, seg.end / duration))
        if progress_cb:
            progress_cb(1.0)
        logger.info(
            "Whisper : %d segments, %.1fs, lang=%s",
            len(out), duration, info.language,
        )
        return TranscriptionResult(
            segments=out, language=info.language, duration=duration, backend="whisper",
        )
