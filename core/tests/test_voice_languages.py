"""Speaking replies in the language they're written in (Kokoro), without loading a model."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from mimi.voice import VoiceService


class FakeKokoro:
    def __init__(self):
        self.calls = []

    def get_voices(self):
        return ["af_heart", "bf_emma", "ef_dora", "em_alex", "ff_siwis", "jf_alpha"]

    def create(self, text, voice, speed, lang):
        self.calls.append((voice, lang))
        return np.zeros(240, dtype=np.float32), 24000


def service(tmp_path: Path) -> tuple[VoiceService, FakeKokoro]:
    v = VoiceService(SimpleNamespace(models=tmp_path))
    v._tts = FakeKokoro()
    (tmp_path / "tts").mkdir()
    for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        (tmp_path / "tts" / f).write_bytes(b"x")
    return v, v._tts


def test_a_reply_in_another_language_is_read_by_that_languages_voice(tmp_path):
    v, k = service(tmp_path)
    v.synthesize("Calienta a la persona poco a poco y dale bebidas tibias.", voice="af_heart")
    v.synthesize("Réchauffez la personne lentement et donnez-lui des boissons tièdes.", voice="bf_emma")
    v.synthesize("Warm the person slowly and give them warm drinks.", voice="bf_emma")
    v.synthesize("Dale agua con sal y azúcar para que no se deshidrate.", voice="em_alex")  # already Spanish: kept
    assert k.calls == [("ef_dora", "es"), ("ff_siwis", "fr-fr"), ("bf_emma", "en-gb"), ("em_alex", "es")]


def test_voices_list_spanish_and_french_with_their_language(tmp_path):
    v, _ = service(tmp_path)
    by_id = {x["id"]: x for x in v.voices()}
    assert by_id["ef_dora"]["language"] == "es" and by_id["ff_siwis"]["language"] == "fr" and by_id["af_heart"]["language"] == "en"
    assert "jf_alpha" not in by_id  # only languages the interface speaks


def test_whisper_can_decode_audio_with_the_installed_pyav():
    """Voice input died on fresh installs when PyAV 19 dropped an argument faster-whisper passes."""
    import io
    import wave

    from faster_whisper.audio import decode_audio

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.zeros(1600, dtype=np.int16).tobytes())
    buf.seek(0)
    assert len(decode_audio(buf, sampling_rate=16000)) == 1600
