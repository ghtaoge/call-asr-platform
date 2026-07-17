import io
import wave

import numpy as np

from app.emotion.acoustic_provider import AcousticEmotionProvider


class FakeEmotionModel:
    def generate(self, **kwargs):
        return [{"labels": ["生气/angry", "中立/neutral"], "scores": [0.8, 0.2]}]


def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    samples = np.zeros(16_000, dtype=np.int16)
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(samples.tobytes())
    return buffer.getvalue()


def test_acoustic_emotion_normalizes_label_confidence_and_valence():
    result = AcousticEmotionProvider(FakeEmotionModel()).analyze(wav_bytes(), 0, 1000)
    assert result.label == "angry"
    assert result.confidence == 0.8
    assert result.score == -0.8
