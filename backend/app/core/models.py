from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Speaker(StrEnum):
    sales = "sales"
    customer = "customer"
    unknown = "unknown"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class EmotionResult(BaseModel):
    label: Literal["positive", "neutral", "negative", "angry", "anxious"]
    score: float = Field(ge=0, le=1)


class SensitiveHit(BaseModel):
    word: str
    level: RiskLevel
    category: str
    start: int
    end: int
    context: str
    speaker: Speaker
    segment_id: str
    start_ms: int
    end_ms: int


class ComplianceHit(BaseModel):
    rule_id: str
    level: RiskLevel
    message: str
    suggestion: str
    segment_id: str


class Segment(BaseModel):
    id: str
    session_id: str
    speaker: Speaker = Speaker.unknown
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str
    translation: str = ""
    language: str = "zh"
    target_language: str = "en"
    emotion: EmotionResult = EmotionResult(label="neutral", score=0.5)
    sensitive_hits: list[SensitiveHit] = Field(default_factory=list)
    compliance_hits: list[ComplianceHit] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    is_final: bool = True


class QualityScore(BaseModel):
    score: int = Field(ge=0, le=100)
    noise_level: Literal["low", "medium", "high"]
    silence_ratio: float = Field(ge=0, le=1)
    sales_talk_ratio: float = Field(ge=0, le=1)
    customer_talk_ratio: float = Field(ge=0, le=1)
    interruptions: int = Field(ge=0)
    negative_emotion_ratio: float = Field(ge=0, le=1)
    risk_hit_count: int = Field(ge=0)
    suggestions: list[str] = Field(default_factory=list)


class CallSummary(BaseModel):
    customer_needs: list[str] = Field(default_factory=list)
    sales_promises: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    follow_up_items: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class OfflineAnalysisResponse(BaseModel):
    session_id: str
    segments: list[Segment]
    quality: QualityScore
    summary: CallSummary
