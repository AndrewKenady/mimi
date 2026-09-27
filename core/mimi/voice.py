"""Speech: faster-whisper for speech-to-text, Kokoro (ONNX) for text-to-speech.

Both run on the CPU so they never compete with the LLM for GPU memory. Models
load lazily and unload after a few idle minutes to give RAM back.
"""

from __future__ import annotations

import io
import re
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from . import log
from .paths import Paths

L = log.get("voice")
IDLE_UNLOAD = 8 * 60

VOICE_INFO = {
    "a": ("American English", "en-us"),
    "b": ("British English", "en-gb"),
}
FEATURED = ["af_heart", "af_bella", "af_nicole", "af_sky", "am_michael", "am_fenrir", "am_puck", "bf_emma", "bf_isabella", "bm_george", "bm_fable"]


class VoiceService:
    def __init__(self, paths: Paths, cores: int = 4):
        self.paths = paths
        self.cores = max(2, cores)
        self._stt: dict[str, object] = {}
        self._tts = None
        self._stt_lock = threading.Lock()
        self._tts_lock = threading.Lock()
        self._last_stt = 0.0
        self._last_tts = 0.0
        self._janitor = threading.Thread(target=self._idle_loop, daemon=True, name="voice-idle")
        self._janitor.start()

    # --- availability -------------------------------------------------------------
    def stt_dir(self, name: str) -> Path:
        return self.paths.models / "whisper" / name

    def stt_available(self, name: str = "small") -> bool:
        return (self.stt_dir(name) / "model.bin").exists()

    def tts_available(self) -> bool:
        return (self.paths.models / "tts" / "kokoro-v1.0.onnx").exists() and (self.paths.models / "tts" / "voices-v1.0.bin").exists()

    def status(self) -> dict:
        return {
            "stt": {"small": self.stt_available("small"), "turbo": self.stt_available("turbo"), "loaded": list(self._stt.keys())},
            "tts": {"available": self.tts_available(), "loaded": self._tts is not None},
        }

    # --- speech to text -----------------------------------------------------------
    def _whisper(self, name: str):
        if name not in self._stt:
            from faster_whisper import WhisperModel

            t0 = time.time()
            self._stt[name] = WhisperModel(str(self.stt_dir(name)), device="cpu", compute_type="int8", cpu_threads=self.cores)
            L.info("whisper %s loaded in %.1fs", name, time.time() - t0)
        return self._stt[name]

    def transcribe(self, audio: bytes | Path, model: str = "small", language: str | None = None, vad: bool = True) -> dict:
        """Short utterances (voice input). Returns text + language + duration."""
        segs = list(self.transcribe_iter(audio, model=model, language=language, vad=vad))
        info = segs[0][1] if segs else {"language": language, "duration": 0.0}
        text = " ".join(s["text"] for s, _ in segs).strip()
        return {"text": text, "language": info.get("language"), "duration": info.get("duration", 0.0),
                "segments": [s for s, _ in segs]}

    def transcribe_iter(self, audio: bytes | Path, model: str = "small", language: str | None = None, vad: bool = True,
                        on_progress: Callable[[float], None] | None = None) -> Iterator[tuple[dict, dict]]:
        if not self.stt_available(model):
            model = "small" if self.stt_available("small") else model
        tmp = None
        if isinstance(audio, (bytes, bytearray)):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".audio")
            tmp.write(audio)
            tmp.close()
            src = tmp.name
        else:
            src = str(audio)
        try:
            with self._stt_lock:
                self._last_stt = time.time()
                w = self._whisper(model)
                segments, info = w.transcribe(
                    src, language=language, vad_filter=vad, beam_size=1 if model == "small" else 2,
                    condition_on_previous_text=False,
                )
                meta = {"language": info.language, "duration": float(info.duration or 0.0)}
                for s in segments:
                    self._last_stt = time.time()
                    if on_progress and meta["duration"]:
                        on_progress(min(1.0, s.end / meta["duration"]))
                    text = s.text.strip()
                    if text:
                        yield {"start": round(s.start, 2), "end": round(s.end, 2), "text": text}, meta
        finally:
            if tmp:
                Path(tmp.name).unlink(missing_ok=True)

    # --- text to speech -------------------------------------------------------------
    def _kokoro(self):
        if self._tts is None:
            from kokoro_onnx import Kokoro

            t0 = time.time()
            d = self.paths.models / "tts"
            self._tts = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
            L.info("kokoro loaded in %.1fs", time.time() - t0)
        return self._tts

    def voices(self) -> list[dict]:
        if not self.tts_available():
            return []
        try:
            names = sorted(self._kokoro().get_voices())
        except Exception:
            names = FEATURED
        out = []
        for n in names:
            region = VOICE_INFO.get(n[:1])
            if not region:
                continue  # English voices only for now
            out.append({
                "id": n,
                "name": n.split("_", 1)[-1].replace("_", " ").title(),
                "accent": region[0],
                "gender": "female" if n[1:2] == "f" else "male",
                "featured": n in FEATURED,
            })
        out.sort(key=lambda v: (not v["featured"], v["accent"], v["name"]))
        return out

    def synthesize(self, text: str, voice: str = "af_heart", speed: float = 1.0) -> bytes:
        text = clean_for_speech(text)
        if not text:
            return _wav(np.zeros(2400, dtype=np.float32), 24000)
        lang = VOICE_INFO.get(voice[:1], VOICE_INFO["a"])[1]
        with self._tts_lock:
            self._last_tts = time.time()
            k = self._kokoro()
            try:
                samples, sr = k.create(text, voice=voice, speed=float(speed), lang=lang)
            except Exception:
                samples, sr = k.create(text, voice="af_heart", speed=float(speed), lang="en-us")
            self._last_tts = time.time()
        return _wav(samples, sr)

    def warm(self) -> None:
        """Load speech-in and speech-out ahead of time (voice mode just opened), so the
        first question isn't slowed by model loading (Whisper ~4 s, Kokoro ~1-3 s)."""
        try:
            if self.stt_available("small"):
                with self._stt_lock:
                    self._whisper("small")
                    self._last_stt = time.time()
            if self.tts_available():
                self.synthesize("Ready.")
        except Exception as e:
            L.warning("voice warm-up failed: %s", e)

    # --- housekeeping ----------------------------------------------------------------
    def _idle_loop(self) -> None:
        while True:
            time.sleep(60)
            now = time.time()
            if self._stt and now - self._last_stt > IDLE_UNLOAD and not self._stt_lock.locked():
                with self._stt_lock:
                    self._stt.clear()
                L.info("unloaded whisper (idle)")
            if self._tts is not None and now - self._last_tts > IDLE_UNLOAD and not self._tts_lock.locked():
                with self._tts_lock:
                    self._tts = None
                L.info("unloaded kokoro (idle)")


def clean_for_speech(text: str) -> str:
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"\[(\d+)\]", "", t)                 # citation markers
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)       # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)   # links → text
    t = re.sub(r"[*_#>`|~]+", "", t)                 # markdown symbols
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t)
    return t.strip()[:2000]


def _wav(samples: np.ndarray, sr: int) -> bytes:
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm16 = (pcm * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()
