"""Résumé de transcription via Ollama (Llama 3.1 8B Instruct)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import ollama

from ..config import OllamaConfig, PromptsConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryResult:
    markdown: str   # bloc Markdown structuré (sections Résumé / Points / Décisions / Actions)
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Summarizer:
    def __init__(self, ollama_cfg: OllamaConfig, prompts: PromptsConfig):
        self.cfg = ollama_cfg
        self.prompts = prompts
        self._client = ollama.Client(host=ollama_cfg.base_url)

    def ensure_model_available(self) -> None:
        """Vérifie que le modèle est connu d'Ollama (sinon erreur claire)."""
        try:
            tags = self._client.list()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Ollama injoignable sur {self.cfg.base_url}") from e
        names = {m.get("name", m.get("model", "")) for m in tags.get("models", [])}
        if not any(n.startswith(self.cfg.model.split(":")[0]) for n in names):
            raise RuntimeError(
                f"Modèle Ollama '{self.cfg.model}' absent. Modèles dispo : {names}"
            )

    def summarize(self, transcript: str) -> SummaryResult:
        """Génère un résumé structuré (Markdown) à partir d'une transcription brute."""
        if not transcript.strip():
            return SummaryResult(markdown="_(Transcription vide)_", model=self.cfg.model)

        user_msg = self.prompts.summary_user_template.format(transcript=transcript)
        logger.info(
            "Résumé Ollama (model=%s, transcript=%d chars, num_gpu=%s, num_ctx=%d)",
            self.cfg.model, len(transcript), self.cfg.num_gpu, self.cfg.num_ctx,
        )
        options: dict = {
            "temperature": 0.2,
            "num_ctx": self.cfg.num_ctx,
        }
        # Passer num_gpu / num_thread seulement si explicites (sinon laisser Ollama décider)
        if self.cfg.num_gpu >= 0:
            options["num_gpu"] = self.cfg.num_gpu
        if self.cfg.num_thread > 0:
            options["num_thread"] = self.cfg.num_thread

        resp = self._client.chat(
            model=self.cfg.model,
            messages=[
                {"role": "system", "content": self.prompts.summary_system},
                {"role": "user", "content": user_msg},
            ],
            options=options,
        )
        content = resp["message"]["content"].strip()
        return SummaryResult(
            markdown=content,
            model=self.cfg.model,
            prompt_tokens=resp.get("prompt_eval_count"),
            completion_tokens=resp.get("eval_count"),
        )
