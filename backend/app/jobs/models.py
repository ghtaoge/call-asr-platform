from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.models import CallSummary, QualityScore, Segment


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class JobStage(StrEnum):
    queued = "queued"
    preparing_audio = "preparing_audio"
    transcribing_sales = "transcribing_sales"
    transcribing_customer = "transcribing_customer"
    merging_segments = "merging_segments"
    analyzing_emotion = "analyzing_emotion"
    scanning_risks = "scanning_risks"
    generating_summary = "generating_summary"
    completed = "completed"
    failed = "failed"


class ModuleStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


# Backward-compatible import name for callers that only manage summaries.
SummaryStatus = ModuleStatus


class ModuleError(BaseModel):
    code: str
    message: str


class JobCreateResponse(BaseModel):
    job_id: str
    session_id: str
    status: JobStatus
    stage: JobStage
    progress: int = Field(ge=0, le=100)


class JobStatusResponse(JobCreateResponse):
    transcript_status: ModuleStatus = ModuleStatus.pending
    emotion_status: ModuleStatus = ModuleStatus.pending
    risk_status: ModuleStatus = ModuleStatus.pending
    quality_status: ModuleStatus = ModuleStatus.pending
    summary_status: ModuleStatus = ModuleStatus.pending
    module_errors: dict[str, ModuleError] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class JobRecord(JobStatusResponse):
    source_type: str
    source_url: str | None = None
    source_path: str | None = None
    source_content_type: str | None = None
    created_at: str
    updated_at: str


class JobAnalysisResponse(BaseModel):
    job_id: str
    session_id: str
    transcript_status: ModuleStatus = ModuleStatus.completed
    emotion_status: ModuleStatus = ModuleStatus.completed
    risk_status: ModuleStatus = ModuleStatus.completed
    quality_status: ModuleStatus = ModuleStatus.completed
    summary_status: ModuleStatus = ModuleStatus.completed
    module_errors: dict[str, ModuleError] = Field(default_factory=dict)
    segments: list[Segment]
    quality: QualityScore | None = None
    summary: CallSummary | None = None


class UrlJobRequest(BaseModel):
    audio_url: str
