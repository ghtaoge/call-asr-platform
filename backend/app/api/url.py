import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.core.models import OfflineAnalysisResponse, UrlAnalysisRequest
from app.sensitive.store import SensitiveStore
from app.sessions.repository import SessionRepository
from app.sessions.service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["url"])

MAX_AUDIO_SIZE = 50 * 1024 * 1024  # 50MB
DOWNLOAD_TIMEOUT = 30.0  # seconds


@router.post("/url", response_model=OfflineAnalysisResponse)
async def create_url_session(request: UrlAnalysisRequest) -> OfflineAnalysisResponse:
    # Validate URL format
    if not request.audio_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="音频 URL 格式不合法")

    # Download audio from remote URL
    try:
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            response = await client.get(request.audio_url, follow_redirects=True)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="下载音频文件超时")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"无法下载音频文件：远程服务器返回 {exc.response.status_code}",
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="无法下载音频文件")

    audio = response.content

    # Validate size
    if len(audio) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="音频文件过大")

    # Validate content type is audio-ish
    content_type = response.headers.get("content-type", "")
    if content_type and not any(
        prefix in content_type for prefix in ("audio/", "application/octet-stream", "binary")
    ):
        raise HTTPException(status_code=400, detail="URL 返回的内容不是有效的音频文件")

    # Reuse existing analysis pipeline
    settings = get_settings()
    sensitive_store = SensitiveStore(settings.sensitive_words_path)
    sensitive_store.reload()
    repository = SessionRepository(settings.database_path)
    service = SessionService(repository, sensitive_store)
    session_id, segments, quality, summary = await service.analyze_offline(
        audio, settings.target_language
    )
    return OfflineAnalysisResponse(
        session_id=session_id, segments=segments, quality=quality, summary=summary
    )
