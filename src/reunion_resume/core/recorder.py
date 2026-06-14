"""Capture synchronisée micro + audio système (loopback) + vidéo écran.

Trois threads producteurs écrivent dans des fichiers distincts pendant la session :
- mic.wav        (sounddevice)
- system.wav     (soundcard, WASAPI loopback)
- screen.mp4     (mss + PyAV H.264, sans audio)

À l'arrêt, les fichiers sont mixés/muxés via mixer.py pour produire le MP4 final.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import av
import mss
import numpy as np
import soundcard as sc
import sounddevice as sd
import soundfile as sf

from ..config import RecordingConfig
from . import mixer

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Audio captures
# ----------------------------------------------------------------------------


class _WavWriterThread(threading.Thread):
    """Base : écrit un flux numpy float32 mono dans un WAV au fur et à mesure."""

    def __init__(self, dst_path: Path, samplerate: int):
        super().__init__(daemon=True)
        self.dst_path = dst_path
        self.samplerate = samplerate
        self._stop_event = threading.Event()
        self._writer: sf.SoundFile | None = None
        self.error: Exception | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def _open(self) -> None:
        self.dst_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = sf.SoundFile(
            str(self.dst_path),
            mode="w",
            samplerate=self.samplerate,
            channels=1,
            subtype="PCM_16",
        )

    def _close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None


class MicCapture(_WavWriterThread):
    """Capture micro via sounddevice (PortAudio)."""

    def __init__(self, dst_path: Path, samplerate: int = 16000, device: int | None = None):
        super().__init__(dst_path, samplerate)
        self.device = device

    def run(self) -> None:
        try:
            self._open()
            assert self._writer is not None
            with sd.InputStream(
                samplerate=self.samplerate,
                channels=1,
                dtype="float32",
                device=self.device,
                blocksize=1024,
            ) as stream:
                while not self._stop_event.is_set():
                    data, _ = stream.read(1024)
                    self._writer.write(data)
        except Exception as e:  # noqa: BLE001
            self.error = e
            logger.exception("Erreur MicCapture")
        finally:
            self._close()


class SystemAudioCapture(_WavWriterThread):
    """Capture audio système via WASAPI loopback (soundcard)."""

    def __init__(self, dst_path: Path, samplerate: int = 16000):
        super().__init__(dst_path, samplerate)

    def run(self) -> None:
        try:
            self._open()
            assert self._writer is not None
            # Speaker par défaut → loopback microphone
            default_speaker = sc.default_speaker()
            loopback = sc.get_microphone(default_speaker.name, include_loopback=True)
            with loopback.recorder(samplerate=self.samplerate, channels=1, blocksize=1024) as rec:
                while not self._stop_event.is_set():
                    data = rec.record(numframes=1024)  # (n, 1) float32
                    self._writer.write(data.astype(np.float32))
        except Exception as e:  # noqa: BLE001
            self.error = e
            logger.exception("Erreur SystemAudioCapture")
        finally:
            self._close()


# ----------------------------------------------------------------------------
# Screen capture
# ----------------------------------------------------------------------------


class ScreenCapture(threading.Thread):
    """Capture vidéo de l'écran via mss → encodage H.264 via PyAV."""

    def __init__(self, dst_path: Path, fps: int = 10, monitor: int = 1):
        super().__init__(daemon=True)
        self.dst_path = dst_path
        self.fps = fps
        self.monitor_idx = monitor
        self._stop_event = threading.Event()
        self.error: Exception | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.dst_path.parent.mkdir(parents=True, exist_ok=True)
        container = None
        try:
            with mss.mss() as sct:
                mon = sct.monitors[self.monitor_idx]
                width, height = mon["width"], mon["height"]
                # Dimensions paires requises par H.264
                width -= width % 2
                height -= height % 2

                container = av.open(str(self.dst_path), mode="w")
                stream = container.add_stream("h264", rate=self.fps)
                stream.width = width
                stream.height = height
                stream.pix_fmt = "yuv420p"
                stream.options = {"preset": "veryfast", "crf": "28"}

                period = 1.0 / self.fps
                next_t = time.monotonic()
                while not self._stop_event.is_set():
                    img = np.array(sct.grab(mon))  # BGRA
                    img = img[:height, :width, :3][:, :, ::-1]  # → RGB
                    frame = av.VideoFrame.from_ndarray(img, format="rgb24")
                    for packet in stream.encode(frame):
                        container.mux(packet)
                    next_t += period
                    sleep = next_t - time.monotonic()
                    if sleep > 0:
                        time.sleep(sleep)
                    else:
                        next_t = time.monotonic()
                # flush
                for packet in stream.encode():
                    container.mux(packet)
        except Exception as e:  # noqa: BLE001
            self.error = e
            logger.exception("Erreur ScreenCapture")
        finally:
            if container is not None:
                container.close()


# ----------------------------------------------------------------------------
# Session
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class MonitorInfo:
    """Description d'un écran. `index` correspond à mss.monitors[index]."""
    index: int               # 0 = tous les écrans combinés, 1+ = écrans physiques
    label: str               # texte affichable dans la GUI
    width: int
    height: int
    left: int
    top: int


def list_monitors() -> list[MonitorInfo]:
    """Énumère les écrans disponibles via mss."""
    out: list[MonitorInfo] = []
    try:
        with mss.mss() as sct:
            for idx, m in enumerate(sct.monitors):
                w, h = m["width"], m["height"]
                left, top = m.get("left", 0), m.get("top", 0)
                if idx == 0:
                    label = f"Tous les écrans ({w}×{h})"
                else:
                    label = f"Écran {idx} — {w}×{h} @ ({left},{top})"
                out.append(MonitorInfo(idx, label, w, h, left, top))
    except Exception as e:  # noqa: BLE001
        logger.exception("Impossible d'énumérer les écrans : %s", e)
    return out


@dataclass
class RecordingSession:
    """Résultat d'une session : chemins des fichiers produits."""

    work_dir: Path
    mic_wav: Path | None
    system_wav: Path | None
    screen_mp4: Path | None
    mixed_audio: Path | None = None
    final_mp4: Path | None = None


class Recorder:
    """Orchestrateur des 3 captures."""

    def __init__(self, cfg: RecordingConfig):
        self.cfg = cfg
        self._mic: MicCapture | None = None
        self._sys: SystemAudioCapture | None = None
        self._screen: ScreenCapture | None = None
        self._session: RecordingSession | None = None

    def start(self, work_dir: Path) -> None:
        work_dir.mkdir(parents=True, exist_ok=True)
        self._session = RecordingSession(
            work_dir=work_dir,
            mic_wav=work_dir / "mic.wav" if self.cfg.mic.enabled else None,
            system_wav=work_dir / "system.wav" if self.cfg.system_audio.enabled else None,
            screen_mp4=work_dir / "screen.mp4" if self.cfg.screen.enabled else None,
        )

        if self._session.mic_wav:
            self._mic = MicCapture(
                self._session.mic_wav,
                samplerate=self.cfg.mic.samplerate,
                device=self.cfg.mic.device,
            )
            self._mic.start()
        if self._session.system_wav:
            self._sys = SystemAudioCapture(
                self._session.system_wav,
                samplerate=self.cfg.system_audio.samplerate,
            )
            self._sys.start()
        if self._session.screen_mp4:
            self._screen = ScreenCapture(
                self._session.screen_mp4,
                fps=self.cfg.screen.fps,
                monitor=self.cfg.screen.monitor,
            )
            self._screen.start()

        logger.info("Recorder démarré dans %s", work_dir)

    def stop(self) -> RecordingSession:
        if self._session is None:
            raise RuntimeError("Recorder non démarré")
        for t in (self._mic, self._sys, self._screen):
            if t is not None:
                t.stop()
        for t in (self._mic, self._sys, self._screen):
            if t is not None:
                t.join(timeout=10)
                if t.error:
                    logger.warning("Thread %s a échoué : %s", type(t).__name__, t.error)

        session = self._session
        self._session = None
        self._mic = self._sys = self._screen = None

        # Post-processing : mix audio + mux MP4 final
        try:
            audio_for_final: Path | None = None
            if session.mic_wav and session.system_wav and \
                    session.mic_wav.exists() and session.system_wav.exists():
                session.mixed_audio = session.work_dir / "mixed.wav"
                mixer.mix_audio(session.mic_wav, session.system_wav, session.mixed_audio)
                audio_for_final = session.mixed_audio
            elif session.mic_wav and session.mic_wav.exists():
                audio_for_final = session.mic_wav
            elif session.system_wav and session.system_wav.exists():
                audio_for_final = session.system_wav

            if session.screen_mp4 and session.screen_mp4.exists() and audio_for_final is not None:
                session.final_mp4 = session.work_dir / "recording.mp4"
                mixer.mux_audio_video(session.screen_mp4, audio_for_final, session.final_mp4)
        except Exception:
            logger.exception("Erreur post-processing recording")

        logger.info("Recorder arrêté. Final : %s", session.final_mp4)
        return session
