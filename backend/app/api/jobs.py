import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

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
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


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

    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=content_type, headers={"Accept-Ranges": "bytes"})
    start, end = _parse_range(range_header, path.stat().st_size)
    length = end - start + 1
    return StreamingResponse(
        _file_range(path, start, length),
        status_code=206,
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{path.stat().st_size}",
            "Content-Length": str(length),
        },
    )


def _parse_range(value: str, size: int) -> tuple[int, int]:
    match = RANGE_PATTERN.fullmatch(value.strip())
    if not match or size <= 0:
        raise HTTPException(status_code=416, detail="无效的音频范围")
    raw_start, raw_end = match.groups()
    if not raw_start and not raw_end:
        raise HTTPException(status_code=416, detail="无效的音频范围")
    if not raw_start:
        suffix = int(raw_end)
        if suffix <= 0:
            raise HTTPException(status_code=416, detail="无效的音频范围")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
    if start >= size or end < start:
        raise HTTPException(status_code=416, detail="无效的音频范围")
    return start, min(end, size - 1)


def _file_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as source:
        source.seek(start)
        while remaining:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
