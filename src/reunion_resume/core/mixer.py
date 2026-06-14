"""Wrapper ffmpeg : extraction audio, mix de pistes, mux audio+vidéo."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from ..paths import ffmpeg_exe

logger = logging.getLogger(__name__)


class FfmpegError(RuntimeError):
    pass


# Empêche l'apparition d'une fenêtre console pour CHAQUE invocation ffmpeg
# (sinon des CMD noirs flashent à chaque extract/mix/mux dans l'app GUI).
_NO_WINDOW_KW: dict = {}
if os.name == "nt":
    _NO_WINDOW_KW["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
    _NO_WINDOW_KW["startupinfo"] = _si


def _run(args: list[str]) -> None:
    logger.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.run(
        [str(ffmpeg_exe()), "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        **_NO_WINDOW_KW,
    )
    if proc.returncode != 0:
        raise FfmpegError(f"ffmpeg a échoué :\n{proc.stderr}")


def extract_audio(src: Path, dst_wav: Path, samplerate: int = 16000) -> Path:
    """Extrait/convertit l'audio en WAV mono PCM 16-bit pour Whisper."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "-i", str(src),
        "-vn",
        "-ac", "1",
        "-ar", str(samplerate),
        "-c:a", "pcm_s16le",
        str(dst_wav),
    ])
    return dst_wav


def mix_audio(mic_wav: Path, sys_wav: Path, dst_wav: Path) -> Path:
    """Mixe deux pistes audio (mic + système) en une seule via amix."""
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "-i", str(mic_wav),
        "-i", str(sys_wav),
        "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=0[a]",
        "-map", "[a]",
        "-c:a", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(dst_wav),
    ])
    return dst_wav


def mux_audio_video(video_in: Path, audio_in: Path, dst_mp4: Path) -> Path:
    """Combine vidéo (sans audio) + piste audio en MP4 final."""
    dst_mp4.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "-i", str(video_in),
        "-i", str(audio_in),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(dst_mp4),
    ])
    return dst_mp4
