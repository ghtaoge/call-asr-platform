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
        """在说话人的独立声道中分析一个 ASR 句段的情绪。

        emotion2vec 接收音频文件而不是字节区间，所以这里只把目标句段写入临时 WAV。
        当前流程只使用分类分数，不需要向量结果，因此关闭 embedding 提取，减少
        不必要的计算和内存消耗。
        """
        clip = self._audio.slice_wav(wav_bytes, start_ms, end_ms)
        temporary = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            temporary.write(clip)
            temporary.close()
            result = self._get_model().generate(
                input=temporary.name,
                granularity="utterance",
                extract_embedding=False,
            )
        finally:
            if not temporary.closed:
                temporary.close()
            try:
                os.unlink(temporary.name)
            except OSError:
                pass
        label, confidence = self._best_result(result)
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
