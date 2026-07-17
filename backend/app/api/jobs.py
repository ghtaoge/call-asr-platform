from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from app.audio.responses import audio_file_response

from app.core.config import get_settings
from app.jobs.manager import JobManager, JobNotReadyError
from app.jobs.models import (
    JobAnalysisResponse,
    JobCreateResponse,
    JobStatusResponse,
    UrlJobRequest,
)
from app.jobs.storage import AudioTooLargeError


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="分析服务尚未就绪")
    return manager


@router.post("/upload", response_model=JobCreateResponse, status_code=202)
async def create_upload_job(request: Request, file: UploadFile = File(...)) -> JobCreateResponse:
    settings = get_settings()
    try:
        audio = await file.read(settings.max_audio_bytes + 1)
    finally:
        await file.close()
    if len(audio) > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="音频文件不能超过 50 MB")
    if not audio:
        raise HTTPException(status_code=400, detail="音频文件为空")
    try:
        return await _manager(request).create_upload(audio, file.content_type or "application/octet-stream")
    except AudioTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.post("/url", response_model=JobCreateResponse, status_code=202)
async def create_url_job(request: Request, body: UrlJobRequest) -> JobCreateResponse:
    return await _manager(request).create_url(body.audio_url)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(request: Request, job_id: str) -> JobStatusResponse:
    try:
        return await _manager(request).get_status(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.get("/{job_id}/result", response_model=JobAnalysisResponse)
async def get_job_result(request: Request, job_id: str) -> JobAnalysisResponse:
    try:
        return await _manager(request).get_result(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except JobNotReadyError as exc:
        raise HTTPException(status_code=409, detail="任务尚未完成") from exc


@router.post("/{job_id}/retry-summary", response_model=JobStatusResponse, status_code=202)
async def retry_summary(request: Request, job_id: str) -> JobStatusResponse:
    try:
        return await _manager(request).retry_summary(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except JobNotReadyError as exc:
        raise HTTPException(status_code=409, detail="当前状态不能重新生成摘要") from exc


RetryModule = Literal["emotion", "risk", "quality", "summary"]


@router.post("/{job_id}/retry/{module}", response_model=JobStatusResponse, status_code=202)
async def retry_module(
    request: Request,
    job_id: str,
    module: RetryModule,
) -> JobStatusResponse:
    try:
        return await _manager(request).retry_module(job_id, module)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except JobNotReadyError as exc:
        raise HTTPException(status_code=409, detail="当前模块状态不能重新分析") from exc


@router.get("/{job_id}/audio")
async def get_job_audio(request: Request, job_id: str):
    try:
        path, content_type = await _manager(request).get_audio(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except JobNotReadyError as exc:
        raise HTTPException(status_code=409, detail="任务音频尚未准备完成") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务音频已过期") from exc

    return audio_file_response(
        path,
        content_type,
        request.headers.get("range"),
    )
