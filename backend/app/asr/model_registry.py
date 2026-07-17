from collections.abc import Callable
import logging
import time
from threading import Lock
from typing import Any


logger = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self, device: str = "cpu", factory: Callable[..., Any] | None = None) -> None:
        self.device = device
        self._factory = factory
        self._sensevoice: Any | None = None
        self._emotion: Any | None = None
        self._streaming_asr: Any | None = None
        self._streaming_vad: Any | None = None
        self._speaker_embedding: Any | None = None
        self._lock = Lock()

    def sensevoice(self) -> Any:
        if self._sensevoice is None:
            with self._lock:
                if self._sensevoice is None:
                    # Paraformer 面向中文转写，并原生输出词级时间戳；CT-Punc 将词级
                    # 时间戳整理成句级区间。15 秒 VAD 上限避免超长语句影响准确率。
                    self._sensevoice = self._create(
                        model="paraformer-zh",
                        vad_model="fsmn-vad",
                        punc_model="ct-punc",
                        vad_kwargs={"max_single_segment_time": 15_000},
                        device=self.device,
                        disable_update=True,
                    )
        return self._sensevoice

    def emotion(self) -> Any:
        if self._emotion is None:
            with self._lock:
                if self._emotion is None:
                    self._emotion = self._create(
                        model="iic/emotion2vec_plus_base",
                        device=self.device,
                        disable_update=True,
                    )
        return self._emotion

    def streaming_asr(self) -> Any:
        if self._streaming_asr is None:
            with self._lock:
                if self._streaming_asr is None:
                    self._streaming_asr = self._create(
                        model="paraformer-zh-streaming",
                        device=self.device,
                        disable_update=True,
                    )
        return self._streaming_asr

    def streaming_vad(self) -> Any:
        if self._streaming_vad is None:
            with self._lock:
                if self._streaming_vad is None:
                    self._streaming_vad = self._create(
                        model="fsmn-vad",
                        device=self.device,
                        disable_update=True,
                    )
        return self._streaming_vad

    def speaker_embedding(self) -> Any:
        if self._speaker_embedding is None:
            with self._lock:
                if self._speaker_embedding is None:
                    self._speaker_embedding = self._create(
                        model="cam++",
                        device=self.device,
                        disable_update=True,
                    )
        return self._speaker_embedding

    def _create(self, **kwargs: Any) -> Any:
        model_name = str(kwargs.get("model", "unknown"))
        started = time.perf_counter()
        logger.info("Loading model: %s", model_name)
        if self._factory is not None:
            model = self._factory(**kwargs)
        else:
            from funasr import AutoModel

            model = AutoModel(**kwargs)
        logger.info("Loaded model: %s in %.2fs", model_name, time.perf_counter() - started)
        return model
