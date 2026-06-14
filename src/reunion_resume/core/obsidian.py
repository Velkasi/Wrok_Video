"""Écriture du résumé Markdown + copie de la vidéo.

Convention de rangement :
  <output.folder>/
    ├── 2026-05-09-1430-reunion-X/             ← Live : sous-dossier dédié
    │   ├── 2026-05-09-1430-reunion-X.mp4
    │   └── 2026-05-09-1430-reunion-X.md
    └── 2026-05-09-1500-fichier-Y.md           ← File : .md à plat (pas de vidéo)

Le `.md` référence la vidéo en chemin relatif (`./fichier.mp4`), utilisable dans
n'importe quel éditeur Markdown (VS Code, Typora, Obsidian si tu pointes ce
dossier dans un vault, etc.).
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from slugify import slugify

from ..config import OutputConfig
from .summarizer import SummaryResult
from .transcriber import TranscriptionResult

logger = logging.getLogger(__name__)


def _format_segments(result: TranscriptionResult) -> str:
    lines = []
    for s in result.segments:
        ts = _hms(s.start)
        text = s.text.strip()
        if text:
            lines.append(f"- **[{ts}]** {text}")
    return "\n".join(lines)


def _hms(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class ObsidianWriter:
    """Écrit `<folder>/<prefix>.md` et copie la vidéo en `<folder>/<prefix>.<ext>`."""

    def __init__(self, output: OutputConfig):
        self.output = output

    def write_summary(
        self,
        title: str,
        transcription: TranscriptionResult,
        summary: SummaryResult,
        source: str,                    # "live" | "file"
        source_path: Path | None = None,
        video_path: Path | None = None,
    ) -> Path:
        date = datetime.now()
        slug = slugify(title or "reunion") or "reunion"
        prefix = f"{date:%Y-%m-%d-%H%M}-{slug}"

        root = self.output.folder
        root.mkdir(parents=True, exist_ok=True)

        # Mode Live (vidéo présente) → sous-dossier dédié
        # Mode File (pas de vidéo)   → .md à plat dans `root`
        has_video = video_path is not None and video_path.exists()
        target_dir = (root / prefix) if has_video else root
        target_dir.mkdir(parents=True, exist_ok=True)

        out_md = target_dir / f"{prefix}.md"

        video_filename: str | None = None
        if has_video:
            assert video_path is not None
            target_video = target_dir / f"{prefix}{video_path.suffix}"
            shutil.copy2(video_path, target_video)
            video_filename = target_video.name
            logger.info("Vidéo copiée : %s", target_video)

        frontmatter: dict = {
            "date": date.strftime("%Y-%m-%d"),
            "time": date.strftime("%H:%M"),
            "type": "meeting-summary",
            "source": source,
            "duration_sec": int(transcription.duration),
            "language": transcription.language,
            "model_summary": summary.model,
            "tags": ["resume-auto", "reunion", "wrok-video"],
        }
        if video_filename:
            # Chemin relatif : fonctionne dans tout viewer Markdown sans logique spéciale
            frontmatter["video"] = f"./{video_filename}"
        if source_path:
            frontmatter["source_file"] = str(source_path)

        body_parts = [
            "---",
            yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
            "---",
            "",
            f"# {title}",
            "",
        ]
        if video_filename:
            body_parts += [
                f"📹 **Vidéo** : [{video_filename}](./{video_filename})",
                "",
            ]
        body_parts += [
            summary.markdown.strip(),
            "",
            "## Transcription complète",
            "",
            "<details><summary>Afficher la transcription</summary>",
            "",
            _format_segments(transcription),
            "",
            "</details>",
            "",
        ]

        out_md.write_text("\n".join(body_parts), encoding="utf-8")
        logger.info("Résumé écrit : %s", out_md)
        return out_md
