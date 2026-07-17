from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.audio.responses import audio_file_response
from app.tts.manager import TtsManager, TtsValidationError
from app.tts.models import TtsJobRequest, TtsJobResponse, TtsVoiceResponse


router = APIRouter(prefix="/api/tts", tags=["tts"])


def _manager(request: Request) -> TtsManager:
    manager = getattr(request.app.state, "tts_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="语音合成服务尚未就绪")
    return manager


@router.post("/voices/clone", response_model=TtsVoiceResponse, status_code=201)
async def clone_voice(
    request: Request,
    file: UploadFile = File(...),
    consent: bool = Form(...),
) -> TtsVoiceResponse:
    try:
        manager = _manager(request)
        max_bytes = getattr(getattr(manager, "storage", None), "max_reference_bytes", 20 * 1024 * 1024)
        audio = await file.read(max_bytes + 1)
    finally:
        await file.close()
    try:
        return await manager.create_voice(audio, file.filename or "", consent)
    except TtsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs", response_model=TtsJobResponse, status_code=202)
async def create_job(request: Request, body: TtsJobRequest) -> TtsJobResponse:
    try:
        return await _manager(request).create_job(body.voice_id, body.text)
    except (TtsValidationError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=TtsJobResponse)
async def get_job(request: Request, job_id: str) -> TtsJobResponse:
    try:
        return await _manager(request).get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="语音合成任务不存在") from exc


@router.get("/jobs/{job_id}/audio")
async def get_audio(request: Request, job_id: str, download: bool = False):
    try:
        path = await _manager(request).get_audio(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="语音合成任务不存在") from exc
    except TtsValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="合成音频已过期") from exc
    return audio_file_response(
        path,
        "audio/wav",
        request.headers.get("range"),
        download_name=f"ai-generated-{job_id}.wav" if download else None,
        extra_headers={
            "X-Audio-Origin": "ai-generated",
            "X-TTS-Model": "Fun-CosyVoice3-0.5B-2512",
        },
    )
