from app.compliance.rules import ComplianceRuleEngine
from app.core.models import EmotionResult, RiskLevel, Segment, SensitiveHit, Speaker
from app.quality.scoring import QualityScorer
from app.summary.generator import SummaryGenerator


def _segment(text: str, speaker: Speaker = Speaker.sales) -> Segment:
    return Segment(
        id="seg_1",
        session_id="s1",
        speaker=speaker,
        start_ms=0,
        end_ms=3000,
        text=text,
        emotion=EmotionResult(label="neutral", score=0.6),
        confidence=0.9,
    )


def test_compliance_detects_absolute_promise():
    engine = ComplianceRuleEngine()

    hits = engine.check(_segment("这个方案绝对有效，请您放心。"))

    assert hits[0].rule_id == "absolute_promise"
    assert hits[0].level == RiskLevel.critical


def test_quality_score_penalizes_risks_and_negative_emotion():
    segment = _segment("客户投诉。", Speaker.customer)
    segment.emotion = EmotionResult(label="angry", score=0.86)
    segment.sensitive_hits = [
        SensitiveHit(
            word="投诉",
            level=RiskLevel.high,
            category="complaint",
            start=2,
            end=4,
            context="客户投诉",
            speaker=Speaker.customer,
            segment_id="seg_1",
            start_ms=0,
            end_ms=3000,
        )
    ]

    score = QualityScorer().score([segment], silence_ratio=0.2, noise_level="medium")

    assert score.score < 90
    assert score.risk_hit_count == 1
    assert score.negative_emotion_ratio == 1


def test_summary_extracts_follow_up_items():
    summary = SummaryGenerator().generate([_segment("客户想了解价格，需要明天跟进。", Speaker.customer)])

    assert "价格咨询" in summary.customer_needs
    assert "明天跟进客户" in summary.follow_up_items
