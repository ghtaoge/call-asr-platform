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
    SummaryStatus,
)
from app.jobs.repository import JobRepository
from app.jobs.storage import AudioTooLargeError, JobStorage
from app.sessions.pipeline import AnalysisPipeline, AnalysisPipelineError, LocalAnalysisResult
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

    async def get_status(self, job_id: str) -> JobStatusResponse:
        record = await self.jobs.require(job_id)
        return JobStatusResponse(**record.model_dump())

    async def get_result(self, job_id: str) -> JobAnalysisResponse:
        record = await self.jobs.require(job_id)
        if record.status != JobStatus.completed:
            raise JobNotReadyError(job_id)
        segments = await self.sessions.list_segments(record.session_id)
        quality = await self.sessions.get_quality(record.session_id)
        if quality is None:
            raise JobNotReadyError(job_id)
        return JobAnalysisResponse(
            job_id=job_id,
            session_id=record.session_id,
            summary_status=record.summary_status,
            summary_error_code=record.error_code if record.summary_status == SummaryStatus.failed else None,
            segments=segments,
            quality=quality,
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
        record = await self.jobs.require(job_id)
        if record.status != JobStatus.completed:
            raise JobNotReadyError(job_id)
        if record.summary_status == SummaryStatus.running:
            raise JobNotReadyError(job_id)
        await self.jobs.set_summary_status(job_id, SummaryStatus.running)
        self._spawn(job_id, self._retry_summary(job_id, record.session_id))
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

            def run_pipeline() -> LocalAnalysisResult:
                return self.pipeline.run(source_path.read_bytes(), record.session_id, progress)

            local_result = await loop.run_in_executor(self.executor, run_pipeline)
            await self.sessions.save_segments(record.session_id, local_result.segments)
            await self.sessions.save_quality(record.session_id, local_result.quality)
            await self._generate_summary(job_id, record.session_id, local_result.segments, initial=True)
            await self.jobs.complete(job_id)
            await self.sessions.set_status(record.session_id, "completed")
        except UnsupportedChannelLayout as exc:
            await self.jobs.fail(job_id, "unsupported_channel_layout", str(exc))
        except AnalysisPipelineError as exc:
            await self.jobs.fail(job_id, exc.code, exc.public_message)
        except Exception:
            logger.exception("Analysis job failed: %s", job_id)
            await self.jobs.fail(job_id, "analysis_failed", "通话分析失败")

    async def _generate_summary(
        self,
        job_id: str,
        session_id: str,
        segments: list,
        initial: bool,
    ) -> None:
        if initial:
            await self.jobs.update_progress(job_id, JobStage.generating_summary, 90)
        await self.jobs.set_summary_status(job_id, SummaryStatus.running)
        try:
            summary = await self.summary.generate(segments)
            await self.sessions.save_summary(session_id, summary)
            await self.jobs.set_summary_status(job_id, SummaryStatus.completed)
        except SummaryError as exc:
            await self.jobs.set_summary_status(
                job_id,
                SummaryStatus.failed,
                exc.code,
                exc.public_message,
            )

    async def _retry_summary(self, job_id: str, session_id: str) -> None:
        segments = await self.sessions.list_segments(session_id)
        await self._generate_summary(job_id, session_id, segments, initial=False)

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
