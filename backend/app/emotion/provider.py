from app.core.models import EmotionResult


class RuleEmotionProvider:
    def analyze(self, text: str) -> EmotionResult:
        angry_words = ("生气", "投诉", "必须", "太差", "骗人")
        anxious_words = ("担心", "害怕", "着急", "焦虑")
        negative_words = ("不满", "失望", "难受", "拒绝")
        positive_words = ("满意", "可以", "谢谢", "不错")
        if any(word in text for word in angry_words):
            return EmotionResult(label="angry", confidence=0.86, score=-0.86)
        if any(word in text for word in anxious_words):
            return EmotionResult(label="anxious", confidence=0.78, score=-0.62)
        if any(word in text for word in negative_words):
            return EmotionResult(label="negative", confidence=0.74, score=-0.48)
        if any(word in text for word in positive_words):
            return EmotionResult(label="positive", confidence=0.72, score=0.72)
        return EmotionResult(label="neutral", confidence=0.62, score=0.0)
