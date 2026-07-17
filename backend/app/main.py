from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, jobs, offline, realtime, tts, url
from app.asr.model_registry import ModelRegistry
from app.asr.sensevoice_provider import SenseVoiceProvider
from app.audio.downloader import SafeAudioDownloader
from app.audio.preprocessor import AudioPreprocessor
from app.compliance.rules import ComplianceRuleEngine
from app.core.config import get_settings
from app.core.inference_gate import InferenceGate
from app.emotion.acoustic_provider import AcousticEmotionProvider
from app.jobs.manager import JobManager
from app.jobs.repository import JobRepository
from app.jobs.storage import JobStorage
from app.quality.scoring import QualityScorer
from app.realtime.manager import RealtimeManager
from app.realtime.speaker_clusterer import TwoSpeakerClusterer
from app.realtime.streaming_asr import FunAsrStreamingProvider
from app.sensitive.store import SensitiveStore
from app.sessions.pipeline import AnalysisPipeline
from app.sessions.repository import SessionRepository
from app.summary.deepseek import DeepSeekSummaryProvider
from app.tts.manager import TtsManager
from app.tts.provider import CosyVoiceWorkerProvider
from app.tts.repository import TtsRepository
from app.tts.storage import TtsStorage


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    jobs_repository = JobRepository(settings.database_path)
    sessions_repository = SessionRepository(settings.database_path)
    await jobs_repository.init()
    await sessions_repository.init()
    await jobs_repository.mark_running_interrupted()

    storage = JobStorage(
        settings.jobs_dir,
        retention_days=settings.job_retention_days,
        max_bytes=settings.max_audio_bytes,
    )
    for expired_job_id in storage.cleanup_expired():
        await jobs_repository.delete(expired_job_id)

    sensitive_store = SensitiveStore(settings.sensitive_words_path)
    sensitive_store.reload()
    registry = ModelRegistry(device=settings.resolved_device)
    audio = AudioPreprocessor()
    asr_provider = SenseVoiceProvider(model_loader=registry.sensevoice)
    pipeline = AnalysisPipeline(
        audio=audio,
        asr=asr_provider,
        emotion=AcousticEmotionProvider(audio=audio, model_loader=registry.emotion),
        sensitive_store=sensitive_store,
        compliance=ComplianceRuleEngine(),
        quality=QualityScorer(),
    )
    manager = JobManager(
        jobs=jobs_repository,
        sessions=sessions_repository,
        storage=storage,
        pipeline=pipeline,
        summary=DeepSeekSummaryProvider(
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_model,
            timeout=settings.deepseek_timeout_seconds,
        ),
        downloader=SafeAudioDownloader(
            settings.max_audio_bytes,
            settings.download_timeout_seconds,
        ),
    )
    app.state.job_manager = manager
    inference_gate = InferenceGate()
    realtime_manager = RealtimeManager(
        repository=sessions_repository,
        jobs=manager,
        pipeline=pipeline,
        asr_provider=FunAsrStreamingProvider(
            registry.streaming_asr,
            registry.streaming_vad,
        ),
        clusterer_factory=lambda: TwoSpeakerClusterer(registry.speaker_embedding),
        data_dir=settings.data_dir / "realtime",
        gate=inference_gate,
    )
    app.state.realtime_manager = realtime_manager
    tts_manager = TtsManager(
        repository=TtsRepository(settings.database_path),
        storage=TtsStorage(settings.tts_dir, settings.tts_max_reference_bytes),
        audio=audio,
        asr=asr_provider,
        provider=CosyVoiceWorkerProvider(
            settings.cosyvoice_worker_url,
            settings.cosyvoice_worker_token,
            settings.cosyvoice_timeout_seconds,
        ),
        gate=inference_gate,
        retention_days=settings.tts_retention_days,
    )
    await tts_manager.start()
    app.state.tts_manager = tts_manager
    try:
        yield
    finally:
        await realtime_manager.close()
        await tts_manager.close()
        await manager.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Call ASR Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:5175",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(offline.router)
    app.include_router(realtime.router)
    app.include_router(url.router)
    app.include_router(jobs.router)
    app.include_router(tts.router)
    return app


app = create_app()
