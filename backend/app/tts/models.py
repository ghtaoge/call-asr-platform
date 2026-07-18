from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class TtsJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class TtsHealthStatus(StrEnum):
    starting = "starting"
    ready = "ready"
    busy = "busy"
    unavailable = "unavailable"


class TtsVoice(BaseModel):
    id: str
    prompt_path: Path
    prompt_text: str
    expires_at: datetime
    created_at: datetime


class TtsJob(BaseModel):
    id: str
    voice_id: str
    text: str
    status: TtsJobStatus
    output_path: Path | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TtsVoiceResponse(BaseModel):
    voice_id: str
    prompt_text: str
    expires_at: datetime


class TtsPresetVoiceResponse(BaseModel):
    id: str
    voice_id: str
    label: str
    language: str
    gender: str


class TtsHealthResponse(BaseModel):
    status: TtsHealthStatus
    model: str | None = None
    queue_depth: int = 0
    error_code: str | None = None
    fallback_available: bool = False
    message: str
    checked_at: datetime


class TtsJobRequest(BaseModel):
    voice_id: str
    text: str = Field(min_length=1, max_length=2000)


class TtsJobResponse(BaseModel):
    job_id: str
    voice_id: str
    status: TtsJobStatus
    error_code: str | None = None
    error_message: str | None = None
