from datetime import datetime
from pydantic import BaseModel, Field


class PbxCallStart(BaseModel):
    source_session_id: str = Field(min_length=1, max_length=128)
    trunk_id: str = Field(min_length=1, max_length=128)
    customer_number: str = ""
    sales_number: str = ""
    role_pending: bool = False


class PbxCallStatus(BaseModel):
    status: str
    role_pending: bool | None = None
    media_interrupted: bool | None = None
    asr_degraded: bool | None = None


class PbxCallResponse(BaseModel):
    id: str
    tenant_id: str
    source_session_id: str
    source: str = "siprec"
    status: str
    started_at: datetime
    updated_at: datetime
    customer_number: str
    sales_number: str
    role_pending: bool
    media_interrupted: bool
    asr_degraded: bool
