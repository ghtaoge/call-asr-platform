import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from app.audio.downloader import DownloadError, SafeAudioDownloader
from app.audio.preprocessor import UnsupportedChannelLayout
from app.jobs.models import (
    JobAnalysisResponse,
    JobCreateResponse,
    JobStage,
    JobStatus,
    JobStatusResponse,
    ModuleStatus,
)
from app.jobs.repository import JobRepository
from app.jobs.storage import AudioTooLargeError, JobStorage
from app.sessions.pipeline import AnalysisPipeline, AnalysisPipelineError, TranscriptionResult
from app.sessions.repository import SessionRepository
from app.summary.deepseek import DeepSeekSummaryProvider, SummaryError


logger = logging.getLogger(__name__)


class JobNotReadyError(RuntimeError):
    pass


class JobManager:
    def __init__(
        self,
        jobs: JobRepository,
        sessions: SessionRepository,
        storage: JobStorage,
        pipeline: AnalysisPipeline,
        summary: DeepSeekSummaryProvider,
        downloader: SafeAudioDownloader,
    ) -> None:
        self.jobs = jobs
        self.sessions = sessions
        self.storage = storage
        self.pipeline = pipeline
        self.summary = summary
        self.downloader = downloader
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="call-analysis")
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def create_upload(self, audio: bytes, content_type: str) -> JobCreateResponse:
        job_id, session_id = self._identifiers()
        record = await self.jobs.create(job_id, session_id, "upload")
        try:
            path = self.storage.save_bytes(job_id, audio)
            await self.jobs.set_source(job_id, path, content_type or "application/octet-stream")
        except AudioTooLargeError:
            await self.jobs.fail(job_id, "audio_too_large", "音频文件不能超过 50 MB")
            raise
        self._spawn(job_id, self._analyze(job_id))
        return self._create_response(record)

    async def create_url(self, audio_url: str) -> JobCreateResponse:
        job_id, session_id = self._identifiers()
        record = await self.jobs.create(
            job_id,
            session_id,
            "url",
            self._display_url(audio_url),
        )
        self._spawn(job_id, self._download_and_analyze(job_id, audio_url))
        return self._create_response(record)

    async def create_realtime_analysis(
        self,
        session_id: str,
        audio: bytes,
        segments: list,
    ) -> JobCreateResponse:
        job_id = f"job_{uuid4().hex[:12]}"
        record = await self.jobs.create(job_id, session_id, "realtime")
        path = self.storage.save_bytes(job_id, audio)
        await self.jobs.set_source(job_id, path, "audio/wav")
        await self.sessions.save_segments(session_id, segments)
        await self.jobs.set_module_status(job_id, "transcript", ModuleStatus.completed)
        self._spawn(job_id, self._analyze_realtime(job_id, session_id, path, segments))
        return self._create_response(record)

    async def get_status(self, job_id: str) -> JobStatusResponse:
        record = await self.jobs.require(job_id)
        return JobStatusResponse(**record.model_dump())

    async def get_result(self, job_id: str) -> JobAnalysisResponse:
        record = await self.jobs.require(job_id)
        if record.transcript_status != ModuleStatus.completed:
            raise JobNotReadyError(job_id)
        return JobAnalysisResponse(
            job_id=job_id,
            session_id=record.session_id,
            transcript_status=record.transcript_status,
            emotion_status=record.emotion_status,
            risk_status=record.risk_status,
            quality_status=record.quality_status,
            summary_status=record.summary_status,
            module_errors=record.module_errors,
            segments=await self.sessions.list_enriched_segments(record.session_id),
            quality=await self.sessions.get_quality(record.session_id),
            summary=await self.sessions.get_summary(record.session_id),
        )

    async def get_audio(self, job_id: str) -> tuple[Path, str]:
        record = await self.jobs.require(job_id)
        if not record.source_path:
            raise JobNotReadyError(job_id)
        path = Path(record.source_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path, record.source_content_type or "application/octet-stream"

    async def retry_summary(self, job_id: str) -> JobStatusResponse:
        return await self.retry_module(job_id, "summary")

    async def retry_module(self, job_id: str, module: str) -> JobStatusResponse:
        if module not in {"emotion", "risk", "quality", "summary"}:
            raise ValueError(f"unsupported analysis module: {module}")
        record = await self.jobs.require(job_id)
        if record.transcript_status != ModuleStatus.completed:
            raise JobNotReadyError(job_id)
        if getattr(record, f"{module}_status") == ModuleStatus.running:
            raise JobNotReadyError(job_id)
        await self.jobs.set_module_status(job_id, module, ModuleStatus.running)
        retry = {
            "emotion": self._retry_emotion,
            "risk": self._retry_risk,
            "quality": self._retry_quality,
            "summary": self._retry_summary,
        }[module]
        self._spawn(
            job_id,
            self._retry_guarded(job_id, record.session_id, module, retry),
        )
        return await self.get_status(job_id)

    async def wait(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.shield(task)

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
        self.executor.shutdown(wait=True, cancel_futures=False)

    async def _download_and_analyze(self, job_id: str, audio_url: str) -> None:
        try:
            await self.jobs.update_progress(job_id, JobStage.preparing_audio, 5)
            destination = self.storage.job_dir(job_id) / "source"
            loop = asyncio.get_running_loop()
            downloaded = await loop.run_in_executor(
                self.executor,
                self.downloader.download,
                audio_url,
                destination,
            )
            await self.jobs.set_source(job_id, downloaded.path, downloaded.content_type)
            await self._analyze(job_id)
        except DownloadError as exc:
            await self.jobs.fail(job_id, exc.code, exc.public_message)
        except Exception:
            logger.exception("URL analysis job failed: %s", job_id)
            await self.jobs.fail(job_id, "download_failed", "无法处理远程语音文件")

    async def _analyze(self, job_id: str) -> None:
        try:
            record = await self.jobs.require(job_id)
            await self.sessions.init()
            await self.sessions.create_session(record.session_id, mode="job")
            if not record.source_path:
                raise AnalysisPipelineError("invalid_audio", "任务音频尚未准备完成")
            source_path = Path(record.source_path)
            loop = asyncio.get_running_loop()

            def progress(stage: JobStage, value: int) -> None:
                future = asyncio.run_coroutine_threadsafe(
                    self.jobs.update_progress(job_id, stage, value),
                    loop,
                )
                future.result()

            await self.jobs.set_module_status(job_id, "transcript", ModuleStatus.running)

            def run_transcription() -> TranscriptionResult:
                return self.pipeline.transcribe(
                    source_path.read_bytes(),
                    record.session_id,
                    progress,
                )

            transcription = await loop.run_in_executor(self.executor, run_transcription)
            await self.sessions.save_segments(record.session_id, transcription.segments)
            await self.jobs.set_module_status(job_id, "transcript", ModuleStatus.completed)
            await self.jobs.update_progress(job_id, JobStage.analyzing_emotion, 72)

            # 三类任务状态和失败相互独立；DeepSeek 网络请求可与本地模型同时运行。
            await asyncio.gather(
                self._run_emotion(job_id, record.session_id, transcription),
                self._run_risk(job_id, record.session_id, transcription.segments),
                self._run_summary(job_id, record.session_id, transcription.segments),
            )
            await self._run_quality(job_id, record.session_id, transcription)
            await self.jobs.complete(job_id)
            await self.sessions.set_status(record.session_id, "completed")
        except UnsupportedChannelLayout as exc:
            await self.jobs.set_module_status(
                job_id,
                "transcript",
                ModuleStatus.failed,
                "unsupported_channel_layout",
                str(exc),
            )
            await self.jobs.fail(job_id, "unsupported_channel_layout", str(exc))
        except AnalysisPipelineError as exc:
            await self.jobs.set_module_status(
                job_id,
                "transcript",
                ModuleStatus.failed,
                exc.code,
                exc.public_message,
            )
            await self.jobs.fail(job_id, exc.code, exc.public_message)
        except Exception:
            logger.exception("Analysis job failed: %s", job_id)
            await self.jobs.fail(job_id, "analysis_failed", "通话分析失败")

    async def _analyze_realtime(
        self,
        job_id: str,
        session_id: str,
        source_path: Path,
        segments: list,
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
            transcription = await loop.run_in_executor(
                self.executor,
                self.pipeline.transcription_from_mono,
                source_path.read_bytes(),
                segments,
            )
            await self.jobs.update_progress(job_id, JobStage.analyzing_emotion, 72)
            await asyncio.gather(
                self._run_emotion(job_id, session_id, transcription),
                self._run_risk(job_id, session_id, segments),
                self._run_summary(job_id, session_id, segments),
            )
            await self._run_quality(job_id, session_id, transcription)
            await self.jobs.complete(job_id)
            await self.sessions.set_status(session_id, "completed")
        except Exception:
            logger.exception("Realtime post-analysis failed: %s", job_id)
            await self.jobs.fail(job_id, "analysis_failed", "实时通话后处理失败")

    async def _run_emotion(
        self,
        job_id: str,
        session_id: str,
        transcription: TranscriptionResult,
    ) -> None:
        await self.jobs.set_module_status(job_id, "emotion", ModuleStatus.running)
        try:
            loop = asyncio.get_running_loop()
            values = await loop.run_in_executor(
                self.executor,
                self.pipeline.analyze_emotion,
                transcription,
            )
            await self.sessions.save_emotions(session_id, values)
            await self.jobs.set_module_status(job_id, "emotion", ModuleStatus.completed)
        except AnalysisPipelineError as exc:
            await self.jobs.set_module_status(
                job_id, "emotion", ModuleStatus.failed, exc.code, exc.public_message
            )
        except Exception:
            logger.exception("Emotion analysis failed: %s", job_id)
            await self.jobs.set_module_status(
                job_id, "emotion", ModuleStatus.failed, "emotion_failed", "通话情绪分析失败"
            )

    async def _run_risk(self, job_id: str, session_id: str, segments: list) -> None:
        await self.jobs.set_module_status(job_id, "risk", ModuleStatus.running)
        try:
            loop = asyncio.get_running_loop()
            values = await loop.run_in_executor(
                self.executor,
                self.pipeline.scan_risks,
                segments,
            )
            await self.sessions.save_risks(session_id, values)
            await self.jobs.set_module_status(job_id, "risk", ModuleStatus.completed)
        except Exception:
            logger.exception("Risk analysis failed: %s", job_id)
            await self.jobs.set_module_status(
                job_id, "risk", ModuleStatus.failed, "risk_failed", "风险与敏感词分析失败"
            )

    async def _run_quality(
        self,
        job_id: str,
        session_id: str,
        transcription: TranscriptionResult,
    ) -> None:
        await self.jobs.set_module_status(job_id, "quality", ModuleStatus.running)
        try:
            segments = await self.sessions.list_enriched_segments(session_id)
            loop = asyncio.get_running_loop()
            quality = await loop.run_in_executor(
                self.executor,
                self.pipeline.score_quality,
                transcription,
                segments,
            )
            record = await self.jobs.require(job_id)
            if record.emotion_status == ModuleStatus.failed:
                quality.suggestions.append("情绪分析不可用，本次质检未计入情绪指标")
            if record.risk_status == ModuleStatus.failed:
                quality.suggestions.append("风险分析不可用，本次质检未计入风险指标")
            await self.sessions.save_quality(session_id, quality)
            await self.jobs.set_module_status(job_id, "quality", ModuleStatus.completed)
        except Exception:
            logger.exception("Quality analysis failed: %s", job_id)
            await self.jobs.set_module_status(
                job_id, "quality", ModuleStatus.failed, "quality_failed", "通话质检失败"
            )

    async def _run_summary(
        self,
        job_id: str,
        session_id: str,
        segments: list,
    ) -> None:
        await self.jobs.set_module_status(job_id, "summary", ModuleStatus.running)
        try:
            summary = await self.summary.generate(segments)
            await self.sessions.save_summary(session_id, summary)
            await self.jobs.set_module_status(job_id, "summary", ModuleStatus.completed)
        except SummaryError as exc:
            await self.jobs.set_module_status(
                job_id,
                "summary",
                ModuleStatus.failed,
                exc.code,
                exc.public_message,
            )
        except Exception:
            logger.exception("Summary generation failed: %s", job_id)
            await self.jobs.set_module_status(
                job_id,
                "summary",
                ModuleStatus.failed,
                "summary_failed",
                "通话摘要生成失败",
            )

    async def _retry_emotion(self, job_id: str, session_id: str) -> None:
        record = await self.jobs.require(job_id)
        if not record.source_path:
            raise JobNotReadyError(job_id)
        segments = await self.sessions.list_segments(session_id)
        loop = asyncio.get_running_loop()
        transcription = await loop.run_in_executor(
            self.executor,
            self.pipeline.restore_transcription,
            Path(record.source_path).read_bytes(),
            segments,
        )
        await self._run_emotion(job_id, session_id, transcription)

    async def _retry_risk(self, job_id: str, session_id: str) -> None:
        await self._run_risk(job_id, session_id, await self.sessions.list_segments(session_id))

    async def _retry_quality(self, job_id: str, session_id: str) -> None:
        record = await self.jobs.require(job_id)
        if not record.source_path:
            raise JobNotReadyError(job_id)
        segments = await self.sessions.list_segments(session_id)
        loop = asyncio.get_running_loop()
        transcription = await loop.run_in_executor(
            self.executor,
            self.pipeline.restore_transcription,
            Path(record.source_path).read_bytes(),
            segments,
        )
        await self._run_quality(job_id, session_id, transcription)

    async def _retry_summary(self, job_id: str, session_id: str) -> None:
        segments = await self.sessions.list_enriched_segments(session_id)
        await self._run_summary(job_id, session_id, segments)

    async def _retry_guarded(
        self,
        job_id: str,
        session_id: str,
        module: str,
        retry,
    ) -> None:
        try:
            await retry(job_id, session_id)
        except Exception:
            logger.exception("Analysis module retry failed: %s/%s", job_id, module)
            await self.jobs.set_module_status(
                job_id,
                module,
                ModuleStatus.failed,
                f"{module}_failed",
                "分析任务重新执行失败",
            )

    def _spawn(self, job_id: str, coroutine) -> None:
        task = asyncio.create_task(coroutine, name=f"analysis-{job_id}")
        self._tasks[job_id] = task

        def remove(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(job_id) is completed:
                self._tasks.pop(job_id, None)

        task.add_done_callback(remove)

    @staticmethod
    def _identifiers() -> tuple[str, str]:
        token = uuid4().hex[:12]
        return f"job_{token}", f"call_{token}"

    @staticmethod
    def _display_url(url: str) -> str:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @staticmethod
    def _create_response(record) -> JobCreateResponse:
        return JobCreateResponse(**record.model_dump())
