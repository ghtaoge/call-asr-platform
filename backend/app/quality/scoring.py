from typing import Literal

from app.core.models import QualityScore, Segment, Speaker


class QualityScorer:
    def score(self, segments: list[Segment], silence_ratio: float, noise_level: Literal["low", "medium", "high"]) -> QualityScore:
        total_duration = sum(max(0, segment.end_ms - segment.start_ms) for segment in segments) or 1
        sales_duration = sum(segment.end_ms - segment.start_ms for segment in segments if segment.speaker == Speaker.sales)
        customer_duration = sum(segment.end_ms - segment.start_ms for segment in segments if segment.speaker == Speaker.customer)
        risk_count = sum(len(segment.sensitive_hits) + len(segment.compliance_hits) for segment in segments)
        negative_count = sum(1 for segment in segments if segment.emotion.label in {"negative", "angry", "anxious"})
        negative_ratio = negative_count / len(segments) if segments else 0
        noise_penalty = {"low": 0, "medium": 6, "high": 14}[noise_level]
        score = 100 - int(silence_ratio * 20) - noise_penalty - risk_count * 8 - int(negative_ratio * 12)
        suggestions: list[str] = []
        if risk_count:
            suggestions.append("本通电话存在风险命中，建议质检人员复核对应片段。")
        if negative_ratio > 0.3:
            suggestions.append("客户负面情绪占比较高，建议优先安排跟进。")
        return QualityScore(
            score=max(0, min(100, score)),
            noise_level=noise_level,
            silence_ratio=silence_ratio,
            sales_talk_ratio=sales_duration / total_duration,
            customer_talk_ratio=customer_duration / total_duration,
            interruptions=0,
            negative_emotion_ratio=negative_ratio,
            risk_hit_count=risk_count,
            suggestions=suggestions,
        )
