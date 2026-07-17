from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile

from app.core.config import get_settings
from app.core.models import CallSummary, OfflineAnalysisResponse
from app.jobs.manager import JobManager, JobNotReadyError
from app.jobs.storage import AudioTooLargeError


router = APIRouter(prefix="/api/sessions", tags=["offline"])


def _manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="分析服务尚未就绪")
    return manager


@router.post("/offline", response_model=OfflineAnalysisResponse, deprecated=True)
async def create_offline_session(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
) -> OfflineAnalysisResponse:
    settings = get_settings()
    try:
        audio = await file.read(settings.max_audio_bytes + 1)
    finally:
        await file.close()
    if len(audio) > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="音频文件不能超过 50 MB")
    if not audio:
        raise HTTPException(status_code=400, detail="音频文件为空")

    manager = _manager(request)
    try:
        job = await manager.create_upload(audio, file.content_type or "application/octet-stream")
        await manager.wait(job.job_id)
        result = await manager.get_result(job.job_id)
    except AudioTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except JobNotReadyError as exc:
        status = await manager.get_status(job.job_id)
        raise HTTPException(status_code=422, detail=status.error_message or "通话分析失败") from exc

    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/jobs/upload>; rel="successor-version"'
    return OfflineAnalysisResponse(
        session_id=result.session_id,
        segments=result.segments,
        quality=result.quality,
        summary=result.summary or CallSummary(),
    )
