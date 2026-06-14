"""Backend NeMo Canary 1B — modèle multilingue FR/EN/DE/ES de NVIDIA.

Nécessite `nemo_toolkit[asr]` (lourd, ~2 GB + torch). Installation :
    uv pip install --python .venv\\Scripts\\python.exe -e ".[canary]"

Le module enregistre le backend uniquement si l'import nemo réussit, sinon
seul la metadata "indisponible" est exposée pour affichage dans la GUI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ...config import TranscriptionConfig
from ...paths import resource_path
from .base import BACKEND_REGISTRY, BackendInfo, Segment, TranscriptionResult

logger = logging.getLogger(__name__)


CANARY_MODELS: dict[str, dict] = {
    "canary-1b-flash": {
        "hf": "nvidia/canary-1b-flash",
        "size_mb": 3000,
        "label": "NeMo Canary 1B Flash (multilingue FR/EN/DE/ES)",
        "languages": ["fr", "en", "de", "es"],
    },
    "canary-1b": {
        "hf": "nvidia/canary-1b",
        "size_mb": 3000,
        "label": "NeMo Canary 1B (multilingue FR/EN/DE/ES)",
        "languages": ["fr", "en", "de", "es"],
    },
}


def _is_nemo_available() -> bool:
    # find_spec("nemo") peut déclencher des imports indirects et crasher dans certains
    # builds PyInstaller où une trace de NeMo a été embarquée à tort. Test ultra-conservateur :
    try:
        import importlib.util
        spec = importlib.util.find_spec("nemo")
        if spec is None:
            return False
        # Vérifie aussi que le sous-module ASR existe (vrai indicateur)
        sub = importlib.util.find_spec("nemo.collections.asr")
        return sub is not None
    except Exception:  # noqa: BLE001
        return False


def _build_info(model_id: str, available: bool) -> BackendInfo:
    info = CANARY_MODELS[model_id]
    suffix = "" if available else "  [installer extra 'canary']"
    return BackendInfo(
        backend="canary",
        model=model_id,
        label=info["label"] + suffix,
        size_mb=info["size_mb"],
        languages=info["languages"],
        requires_gpu=True,
        available=available,
        notes="Top qualité multilingue. GPU recommandé (~3 GB VRAM).",
    )


# ---------------------------------------------------------------------------
# Backend (enregistrement conditionnel)
# ---------------------------------------------------------------------------

_NEMO_OK = _is_nemo_available()


if _NEMO_OK:
    # Import différé pour éviter de charger nemo si le user choisit Whisper
    class CanaryBackend:
        """NeMo Canary 1B — multilingue FR/EN/DE/ES."""

        def __init__(self, cfg: TranscriptionConfig):
            self.cfg = cfg
            # Chemin local préféré, sinon HF identifier
            embedded = resource_path("models", f"canary-{cfg.model}")
            model_path = str(embedded) if embedded.exists() else (
                CANARY_MODELS.get(cfg.model, {}).get("hf", cfg.model)
            )

            # Import nemo ICI (lazy) — évite le coût torch au démarrage de l'app
            from nemo.collections.asr.models import EncDecMultiTaskModel  # type: ignore

            logger.info("CanaryBackend : chargement %s", model_path)
            if Path(model_path).exists():
                self._model = EncDecMultiTaskModel.restore_from(model_path)
            else:
                self._model = EncDecMultiTaskModel.from_pretrained(model_path)

            # Choix device : GPU si dispo
            try:
                import torch  # type: ignore
                if torch.cuda.is_available() and (cfg.device in ("auto", "cuda")):
                    self._model = self._model.to("cuda")
                    logger.info("Canary : device=cuda")
                else:
                    logger.info("Canary : device=cpu")
            except Exception:  # noqa: BLE001
                logger.exception("Canary : impossible de détecter le device, fallback CPU")

        @classmethod
        def name(cls) -> str:
            return "canary"

        @classmethod
        def available_models(cls) -> list[BackendInfo]:
            return [_build_info(m, available=True) for m in CANARY_MODELS]

        def transcribe(
            self,
            audio_path: Path | str,
            progress_cb: Callable[[float], None] | None = None,
        ) -> TranscriptionResult:
            audio_path = Path(audio_path)
            if progress_cb:
                progress_cb(0.05)

            # Canary attend une liste de fichiers et retourne une liste de transcripts
            # source_lang / target_lang : utilise la langue config (translation possible)
            lang = self.cfg.language or "fr"
            result = self._model.transcribe(
                [str(audio_path)],
                source_lang=lang,
                target_lang=lang,
                task="asr",  # transcription pure (pas traduction)
                pnc="yes",   # ponctuation + casse
            )
            # result est une liste : List[str] ou List[Hypothesis] selon version NeMo
            text = result[0] if isinstance(result[0], str) else getattr(result[0], "text", str(result[0]))

            # Durée audio (via soundfile)
            duration = 0.0
            try:
                import soundfile as sf
                with sf.SoundFile(str(audio_path)) as f:
                    duration = f.frames / max(f.samplerate, 1)
            except Exception:  # noqa: BLE001
                pass

            # Pas de segmentation native chez Canary → un seul segment couvrant tout
            segments = [Segment(start=0.0, end=duration, text=text.strip())]
            if progress_cb:
                progress_cb(1.0)
            logger.info("Canary : %d chars, %.1fs, lang=%s", len(text), duration, lang)
            return TranscriptionResult(
                segments=segments, language=lang, duration=duration, backend="canary",
            )

    BACKEND_REGISTRY["canary"] = CanaryBackend  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Listing pour GUI : retourne les modèles même si la dep n'est pas installée
# ---------------------------------------------------------------------------

def list_canary_models() -> list[BackendInfo]:
    return [_build_info(m, available=_NEMO_OK) for m in CANARY_MODELS]


# Patch léger pour que `list_available_backends` puisse récupérer les infos
# même quand le backend n'est pas instanciable :
if not _NEMO_OK:
    # On enregistre un faux backend qui n'expose que les métadonnées
    class _CanaryPlaceholder:
        @classmethod
        def name(cls) -> str:
            return "canary"

        @classmethod
        def available_models(cls) -> list[BackendInfo]:
            return list_canary_models()

        def __init__(self, cfg: TranscriptionConfig):
            raise ImportError(
                "Backend Canary indisponible : installer 'nemo_toolkit' via "
                "`uv pip install -e \".[canary]\"`"
            )

        def transcribe(self, *_args, **_kwargs):  # noqa: D401
            raise NotImplementedError

    BACKEND_REGISTRY["canary"] = _CanaryPlaceholder  # type: ignore[assignment]
