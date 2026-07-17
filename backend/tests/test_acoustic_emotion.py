import io
import wave

import numpy as np

from app.emotion.acoustic_provider import AcousticEmotionProvider


class FakeEmotionModel:
    def __init__(self):
        self.kwargs = None

    def generate(self, **kwargs):
        self.kwargs = kwargs
        count = len(kwargs["input"]) if isinstance(kwargs["input"], list) else 1
        return [
            {"labels": ["生气/angry", "中立/neutral"], "scores": [0.8, 0.2]}
            for _ in range(count)
        ]


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
    model = FakeEmotionModel()
    result = AcousticEmotionProvider(model).analyze(wav_bytes(), 0, 1000)
    assert result.label == "angry"
    assert result.confidence == 0.8
    assert result.score == -0.8
    assert model.kwargs["extract_embedding"] is False


def test_acoustic_emotion_batches_segments_and_caps_long_windows():
    class RecordingAudio:
        def __init__(self):
            self.calls = []

        def slice_wav(self, audio, start, end):
            self.calls.append((audio, start, end))
            return b"clip"

    model = FakeEmotionModel()
    audio = RecordingAudio()
    results = AcousticEmotionProvider(model=model, audio=audio).analyze_many([
        (b"sales", 0, 10_000),
        (b"customer", 1_000, 3_000),
    ])

    assert audio.calls == [
        (b"sales", 3_000, 7_000),
        (b"customer", 1_000, 3_000),
    ]
    assert isinstance(model.kwargs["input"], list)
    assert len(model.kwargs["input"]) == 2
    assert model.kwargs["batch_size"] == 32
    assert [item.label for item in results] == ["angry", "angry"]
