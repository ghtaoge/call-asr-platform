from fastapi import APIRouter, File, UploadFile

from app.core.config import get_settings
from app.core.models import OfflineAnalysisResponse
from app.sensitive.store import SensitiveStore
from app.sessions.repository import SessionRepository
from app.sessions.service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["offline"])


@router.post("/offline", response_model=OfflineAnalysisResponse)
async def create_offline_session(file: UploadFile = File(...)) -> OfflineAnalysisResponse:
    settings = get_settings()
    sensitive_store = SensitiveStore(settings.sensitive_words_path)
    sensitive_store.reload()
    repository = SessionRepository(settings.database_path)
    service = SessionService(repository, sensitive_store)
    audio = await file.read()
    session_id, segments, quality, summary = await service.analyze_offline(audio, settings.target_language)
    return OfflineAnalysisResponse(session_id=session_id, segments=segments, quality=quality, summary=summary)
