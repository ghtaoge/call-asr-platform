import re
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np


TAG_PATTERN = re.compile(r"<\|[^|]+\|>")


@dataclass(frozen=True)
class StreamingRecognition:
    text: str
    endpoint: bool


def _text(result: Any) -> str:
    if not result:
        return ""
    item = result[0] if isinstance(result, list) else result
    if isinstance(item, dict):
        value = item.get("text") or item.get("value") or ""
    else:
        value = item
    return TAG_PATTERN.sub("", str(value)).strip()


def _has_endpoint(result: Any) -> bool:
    if not result:
        return False
    item = result[0] if isinstance(result, list) else result
    value = item.get("value", []) if isinstance(item, dict) else []
    for interval in value or []:
        if isinstance(interval, (list, tuple)) and len(interval) >= 2 and interval[1] >= 0:
            return True
    return False


def _append_with_overlap(existing: str, addition: str) -> str:
    if not addition:
        return existing
    if addition.startswith(existing):
        return addition
    if existing.endswith(addition):
        return existing
    overlap = min(len(existing), len(addition))
    while overlap and existing[-overlap:] != addition[:overlap]:
        overlap -= 1
    return existing + addition[overlap:]


class FunAsrStreamingSession:
    def __init__(self, model: Any, vad: Any) -> None:
        self.model = model
        self.vad = vad
        self.asr_cache: dict[str, Any] = {}
        self.vad_cache: dict[str, Any] = {}
        self.text = ""

    def feed(self, pcm16: bytes, is_final: bool = False) -> StreamingRecognition:
        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        asr_result = self.model.generate(
            input=samples,
            cache=self.asr_cache,
            is_final=is_final,
            chunk_size=[0, 10, 5],
            encoder_chunk_look_back=4,
            decoder_chunk_look_back=1,
            disable_pbar=True,
        )
        vad_result = self.vad.generate(
            input=samples,
            cache=self.vad_cache,
            is_final=is_final,
            disable_pbar=True,
        )
        self.text = _append_with_overlap(self.text, _text(asr_result))
        return StreamingRecognition(self.text, is_final or _has_endpoint(vad_result))

    def reset_sentence(self) -> None:
        self.asr_cache = {}
        self.vad_cache = {}
        self.text = ""


class FunAsrStreamingProvider:
    def __init__(
        self,
        model_loader: Callable[[], Any],
        vad_loader: Callable[[], Any],
    ) -> None:
        self.model_loader = model_loader
        self.vad_loader = vad_loader

    def open_session(self) -> FunAsrStreamingSession:
        return FunAsrStreamingSession(self.model_loader(), self.vad_loader())
