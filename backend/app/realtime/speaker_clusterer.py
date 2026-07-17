import io
import wave
from typing import Any, Callable

import numpy as np


def _wav_bytes(pcm16: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(pcm16)
    return output.getvalue()


def _embedding(result: Any) -> np.ndarray:
    item = result[0] if isinstance(result, list) and result else result
    if isinstance(item, dict):
        value = item.get("spk_embedding")
        if value is None:
            value = item.get("embedding")
        if value is None:
            value = item.get("value")
    else:
        value = item
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not vector.size or norm == 0:
        raise ValueError("speaker model returned no embedding")
    return vector / norm


class TwoSpeakerClusterer:
    def __init__(
        self,
        model_loader: Callable[[], Any],
        threshold: float = 0.72,
    ) -> None:
        self.model_loader = model_loader
        self.threshold = threshold
        self.centroids: list[np.ndarray] = []

    def warmup(self) -> None:
        self.model_loader()

    def assign(self, pcm16: bytes) -> str | None:
        if len(pcm16) < int(16_000 * 2 * 0.8):
            return None
        model = self.model_loader()
        result = model.generate(input=_wav_bytes(pcm16), disable_pbar=True)
        vector = _embedding(result)
        if not self.centroids:
            self.centroids.append(vector)
            return "speaker_1"
        similarities = [float(np.dot(vector, centroid)) for centroid in self.centroids]
        if len(self.centroids) == 1 and similarities[0] < self.threshold:
            self.centroids.append(vector)
            return "speaker_2"
        index = int(np.argmax(similarities))
        updated = self.centroids[index] * 0.8 + vector * 0.2
        self.centroids[index] = updated / np.linalg.norm(updated)
        return f"speaker_{index + 1}"
