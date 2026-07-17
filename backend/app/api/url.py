from fastapi import APIRouter, HTTPException, Request, Response

from app.core.models import CallSummary, OfflineAnalysisResponse, UrlAnalysisRequest
from app.jobs.manager import JobManager, JobNotReadyError


router = APIRouter(prefix="/api/sessions", tags=["url"])


def _manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="分析服务尚未就绪")
    return manager


@router.post("/url", response_model=OfflineAnalysisResponse, deprecated=True)
async def create_url_session(
    request: Request,
    response: Response,
    body: UrlAnalysisRequest,
) -> OfflineAnalysisResponse:
    if not body.audio_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="音频 URL 格式不合法")

    manager = _manager(request)
    job = await manager.create_url(body.audio_url)
    await manager.wait(job.job_id)
    try:
        result = await manager.get_result(job.job_id)
    except JobNotReadyError as exc:
        status = await manager.get_status(job.job_id)
        code = 400 if status.error_code in {"invalid_url", "blocked_url", "invalid_audio"} else 502
        raise HTTPException(status_code=code, detail=status.error_message or "远程音频分析失败") from exc

    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/jobs/url>; rel="successor-version"'
    return OfflineAnalysisResponse(
        session_id=result.session_id,
        segments=result.segments,
        quality=result.quality,
        summary=result.summary or CallSummary(),
    )
