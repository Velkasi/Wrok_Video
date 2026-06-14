"""Interface commune des backends de transcription."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ...config import TranscriptionConfig


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[Segment]
    language: str
    duration: float
    backend: str = ""

    @property
    def full_text(self) -> str:
        return "\n".join(s.text.strip() for s in self.segments if s.text.strip())


@dataclass(frozen=True)
class BackendInfo:
    """Métadonnées d'un modèle exposable dans la GUI."""

    backend: str                 # nom du backend (ex. 'whisper', 'canary')
    model: str                   # identifiant modèle (ex. 'medium', 'large-v3-turbo', 'canary-1b-flash')
    label: str                   # libellé affichable
    size_mb: int                 # taille disque estimée
    languages: list[str] = field(default_factory=list)   # langues supportées
    requires_gpu: bool = False
    available: bool = True       # False si la dépendance n'est pas installée
    notes: str = ""


@runtime_checkable
class TranscriptionBackend(Protocol):
    """Interface qu'un backend doit implémenter."""

    @classmethod
    def name(cls) -> str:
        """Identifiant court du backend (ex. 'whisper', 'canary')."""
        ...

    @classmethod
    def available_models(cls) -> list[BackendInfo]:
        """Modèles que ce backend sait charger (avec statut de disponibilité)."""
        ...

    def transcribe(
        self,
        audio_path: Path | str,
        progress_cb: Callable[[float], None] | None = None,
    ) -> TranscriptionResult:
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BACKEND_REGISTRY: dict[str, type[TranscriptionBackend]] = {}


def register_backend(cls: type[TranscriptionBackend]) -> type[TranscriptionBackend]:
    BACKEND_REGISTRY[cls.name()] = cls
    return cls


def get_backend(cfg: TranscriptionConfig) -> TranscriptionBackend:
    """Instancie le backend correspondant à `cfg.backend`."""
    backend_cls = BACKEND_REGISTRY.get(cfg.backend)
    if backend_cls is None:
        # Import différé pour donner une chance au backend de s'enregistrer
        if cfg.backend == "canary":
            try:
                from . import canary  # noqa: F401  (force registration)
                backend_cls = BACKEND_REGISTRY.get(cfg.backend)
            except ImportError as e:
                raise ImportError(
                    f"Backend 'canary' indisponible : {e}. "
                    "Installer avec : uv pip install -e \".[canary]\""
                ) from e
        if backend_cls is None:
            raise ValueError(
                f"Backend inconnu : '{cfg.backend}'. "
                f"Backends disponibles : {sorted(BACKEND_REGISTRY)}"
            )
    return backend_cls(cfg)  # type: ignore[call-arg]


def list_available_backends() -> list[BackendInfo]:
    """Liste TOUS les modèles connus (incl. ceux dont la dep n'est pas installée).

    Sert au combobox GUI pour montrer ce qui est sélectionnable + statut.
    """
    # On essaie d'importer les backends optionnels pour récolter leurs infos
    try:
        from . import canary  # noqa: F401
    except ImportError:
        pass

    out: list[BackendInfo] = []
    for backend_cls in BACKEND_REGISTRY.values():
        out.extend(backend_cls.available_models())
    return out
