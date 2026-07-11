from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AudioProcessingResult:
    audio: bytes
    silence_ratio: float
    noise_level: Literal["low", "medium", "high"]


class AudioPreprocessor:
    def process(self, audio: bytes) -> AudioProcessingResult:
        if not audio:
            return AudioProcessingResult(audio=b"", silence_ratio=1.0, noise_level="low")
        silence_ratio = 0.1 if len(audio) > 10 else 0.4
        noise_level: Literal["low", "medium", "high"] = "medium" if len(audio) > 0 else "low"
        return AudioProcessingResult(audio=audio, silence_ratio=silence_ratio, noise_level=noise_level)
