import os
import tempfile
from collections.abc import Callable
from typing import Any

from app.audio.preprocessor import AudioPreprocessor
from app.core.models import EmotionResult


LABEL_ALIASES = {
    "happy": "positive",
    "positive": "positive",
    "高兴": "positive",
    "开心": "positive",
    "neutral": "neutral",
    "中立": "neutral",
    "sad": "negative",
    "negative": "negative",
    "悲伤": "negative",
    "angry": "angry",
    "生气": "angry",
    "愤怒": "angry",
    "fear": "anxious",
    "fearful": "anxious",
    "anxious": "anxious",
    "害怕": "anxious",
    "焦虑": "anxious",
    "disgusted": "negative",
    "disgust": "negative",
    "厌恶": "negative",
}

VALENCE = {
    "positive": 1.0,
    "neutral": 0.0,
    "negative": -0.65,
    "angry": -1.0,
    "anxious": -0.8,
}
MAX_EMOTION_WINDOW_MS = 4_000
EMOTION_BATCH_SIZE = 32


class AcousticEmotionProvider:
    def __init__(
        self,
        model: Any | None = None,
        audio: AudioPreprocessor | None = None,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._model = model
        self._model_loader = model_loader
        self._audio = audio or AudioPreprocessor()

    def analyze(self, wav_bytes: bytes, start_ms: int, end_ms: int) -> EmotionResult:
        return self.analyze_many([(wav_bytes, start_ms, end_ms)])[0]

    def analyze_many(
        self,
        requests: list[tuple[bytes, int, int]],
    ) -> list[EmotionResult]:
        """批量分析 ASR 句段，并保持输出与输入顺序一致。

        长句只截取中间四秒。情绪识别需要声学特征，但不需要把十几秒的完整句子
        重复送入模型；居中窗口也能避开句首和句尾常见的短暂停顿。所有片段通过
        一次 ``generate`` 调用提交，减少逐句调度开销。
        """
        if not requests:
            return []
        temporary_paths: list[str] = []
        try:
            for wav_bytes, start_ms, end_ms in requests:
                window_start, window_end = self._emotion_window(start_ms, end_ms)
                clip = self._audio.slice_wav(wav_bytes, window_start, window_end)
                temporary = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                try:
                    temporary.write(clip)
                finally:
                    temporary.close()
                temporary_paths.append(temporary.name)
            result = self._get_model().generate(
                input=temporary_paths,
                granularity="utterance",
                extract_embedding=False,
                batch_size=EMOTION_BATCH_SIZE,
                disable_pbar=True,
            )
        finally:
            for path in temporary_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if not isinstance(result, list) or len(result) != len(requests):
            raise RuntimeError("emotion result count does not match input segments")
        return [self._normalize_result(item) for item in result]

    @staticmethod
    def _emotion_window(start_ms: int, end_ms: int) -> tuple[int, int]:
        duration = end_ms - start_ms
        if duration <= MAX_EMOTION_WINDOW_MS:
            return start_ms, end_ms
        offset = (duration - MAX_EMOTION_WINDOW_MS) // 2
        window_start = start_ms + offset
        return window_start, window_start + MAX_EMOTION_WINDOW_MS

    @classmethod
    def _normalize_result(cls, item: Any) -> EmotionResult:
        label, confidence = cls._best_result([item])
        # 低置信度或未映射的类别统一展示为平静，避免微弱的声学猜测在曲线上
        # 形成误导性的风险尖峰。
        if confidence < 0.35 or label not in VALENCE:
            return EmotionResult(label="neutral", confidence=confidence, score=0.0)
        return EmotionResult(
            label=label,
            confidence=confidence,
            score=round(VALENCE[label] * confidence, 4),
        )

    def _get_model(self) -> Any:
        if self._model is None and self._model_loader is not None:
            self._model = self._model_loader()
        if self._model is None:
            raise RuntimeError("emotion model is not configured")
        return self._model

    @staticmethod
    def _best_result(result: Any) -> tuple[str, float]:
        if not result or not isinstance(result, list) or not isinstance(result[0], dict):
            return "neutral", 0.0
        item = result[0]
        labels = item.get("labels") or item.get("label") or []
        scores = item.get("scores") or item.get("score") or []
        if isinstance(labels, str):
            labels = [labels]
        if isinstance(scores, (int, float)):
            scores = [scores]
        if not labels or not scores:
            return "neutral", 0.0
        index = max(range(min(len(labels), len(scores))), key=lambda position: float(scores[position]))
        raw_label = str(labels[index]).lower()
        normalized = "neutral"
        for alias, product_label in LABEL_ALIASES.items():
            if alias in raw_label:
                normalized = product_label
                break
        return normalized, max(0.0, min(1.0, float(scores[index])))
