from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.models import RiskLevel


class SensitiveWordCreate(BaseModel):
    word: str = Field(min_length=1, max_length=256)
    level: RiskLevel
    category: str = Field(min_length=1, max_length=64)
    enabled: bool = True


class SensitiveWordUpdate(BaseModel):
    word: str | None = Field(default=None, min_length=1, max_length=256)
    level: RiskLevel | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None


class SensitiveWordResponse(BaseModel):
    id: str
    word: str
    normalized_word: str
    level: RiskLevel
    category: str
    enabled: bool
    version: int
    updated_at: datetime


class SensitiveWordListResponse(BaseModel):
    items: list[SensitiveWordResponse]
    next_cursor: str | None = None
    version: int
