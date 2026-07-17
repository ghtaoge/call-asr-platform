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


class SummaryStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobCreateResponse(BaseModel):
    job_id: str
    session_id: str
    status: JobStatus
    stage: JobStage
    progress: int = Field(ge=0, le=100)


class JobStatusResponse(JobCreateResponse):
    summary_status: SummaryStatus
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
    summary_status: SummaryStatus
    summary_error_code: str | None = None
    segments: list[Segment]
    quality: QualityScore
    summary: CallSummary | None = None


class UrlJobRequest(BaseModel):
    audio_url: str
