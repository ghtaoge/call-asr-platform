from collections.abc import Callable
from threading import Lock
from typing import Any


class ModelRegistry:
    def __init__(self, device: str = "cpu", factory: Callable[..., Any] | None = None) -> None:
        self.device = device
        self._factory = factory
        self._sensevoice: Any | None = None
        self._emotion: Any | None = None
        self._lock = Lock()

    def sensevoice(self) -> Any:
        if self._sensevoice is None:
            with self._lock:
                if self._sensevoice is None:
                    self._sensevoice = self._create(
                        model="iic/SenseVoiceSmall",
                        vad_model="fsmn-vad",
                        punc_model="ct-punc",
                        vad_kwargs={"max_single_segment_time": 30_000},
                        device=self.device,
                        trust_remote_code=True,
                        disable_update=True,
                    )
        return self._sensevoice

    def emotion(self) -> Any:
        if self._emotion is None:
            with self._lock:
                if self._emotion is None:
                    self._emotion = self._create(
                        model="iic/emotion2vec_plus_large",
                        device=self.device,
                        disable_update=True,
                    )
        return self._emotion

    def _create(self, **kwargs: Any) -> Any:
        if self._factory is not None:
            return self._factory(**kwargs)
        from funasr import AutoModel

        return AutoModel(**kwargs)
