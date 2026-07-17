import asyncio
import logging
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.asr.sensevoice_provider import SenseVoiceProvider
from app.audio.preprocessor import AudioPreprocessor
from app.core.inference_gate import InferenceGate
from app.core.models import Speaker
from app.tts.models import TtsJob, TtsJobResponse, TtsJobStatus, TtsVoiceResponse
from app.tts.provider import CosyVoiceWorkerProvider, TtsProviderError
from app.tts.repository import TtsRepository, VoiceExpiredError
from app.tts.storage import TtsStorage, TtsStorageLimitError


logger = logging.getLogger(__name__)


class TtsValidationError(ValueError):
    pass


class TtsManager:
    def __init__(
        self,
        repository: TtsRepository,
        storage: TtsStorage,
        audio: AudioPreprocessor,
        asr: SenseVoiceProvider,
        provider: CosyVoiceWorkerProvider,
        gate: InferenceGate,
        retention_days: int,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.audio = audio
        self.asr = asr
        self.provider = provider
        self.gate = gate
        self.retention_days = retention_days
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-reference")
        self.worker: asyncio.Task[None] | None = None
        self._completed: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        await self.repository.init()
        await self.repository.mark_running_failed()
        now = datetime.now(UTC)
        voice_ids, job_ids = await self.repository.delete_expired(
            now,
            now - timedelta(days=self.retention_days),
        )
        for voice_id in voice_ids:
            self.storage.delete_voice(voice_id)
        for job_id in job_ids:
            self.storage.delete_job(job_id)
        self.worker = asyncio.create_task(self._run_queue(), name="tts-queue")

    async def create_voice(
        self,
        audio: bytes,
        filename: str,
        consent: bool,
    ) -> TtsVoiceResponse:
        if not consent:
            raise TtsValidationError("请先确认已获得声音使用授权")
        suffix = Path(filename).suffix.lower()
        voice_id = f"voice_{uuid4().hex[:16]}"
        try:
            self.storage.save_reference(voice_id, audio, suffix)
            loop = asyncio.get_running_loop()
            normalized = await loop.run_in_executor(
                self.executor,
                self.audio.normalize_mono_wav,
                audio,
            )
            prompt_path = self.storage.prompt_path(voice_id)
            prompt_path.write_bytes(normalized)
            with wave.open(str(prompt_path), "rb") as reader:
                duration = reader.getnframes() / reader.getframerate()
            if not 3.0 <= duration <= 30.0:
                raise TtsValidationError("参考音频时长必须在 3 到 30 秒之间")
            await self.gate.wait_for_background_slot()
            segments = await loop.run_in_executor(
                self.executor,
                self.asr.transcribe,
                normalized,
                voice_id,
                Speaker.unknown,
            )
            prompt_text = "".join(segment.text for segment in segments).strip()
            if not prompt_text:
                raise TtsValidationError("参考音频中未识别到有效人声")
            voice = await self.repository.create_voice(
                voice_id,
                prompt_path,
                prompt_text,
                datetime.now(UTC) + timedelta(days=self.retention_days),
            )
            return TtsVoiceResponse(
                voice_id=voice.id,
                prompt_text=voice.prompt_text,
                expires_at=voice.expires_at,
            )
        except (TtsStorageLimitError, TtsValidationError):
            self.storage.delete_voice(voice_id)
            raise
        except Exception as exc:
            self.storage.delete_voice(voice_id)
            raise TtsValidationError("参考音频无法处理") from exc

    async def create_job(self, voice_id: str, text: str) -> TtsJobResponse:
        normalized = text.strip()
        if not normalized or len(normalized) > 2000:
            raise TtsValidationError("合成文本必须为 1 到 2000 个字符")
        job_id = f"tts_{uuid4().hex[:16]}"
        try:
            job = await self.repository.create_job(job_id, voice_id, normalized)
        except VoiceExpiredError as exc:
            raise TtsValidationError("临时音色已过期，请重新上传参考音频") from exc
        self._completed[job_id] = asyncio.Event()
        await self.queue.put(job_id)
        return self._response(job)

    async def get_job(self, job_id: str) -> TtsJobResponse:
        return self._response(await self.repository.require_job(job_id))

    async def get_audio(self, job_id: str) -> Path:
        job = await self.repository.require_job(job_id)
        if job.status != TtsJobStatus.completed or not job.output_path:
            raise TtsValidationError("合成音频尚未生成")
        if not job.output_path.is_file():
            raise FileNotFoundError(job.output_path)
        return job.output_path

    async def wait(self, job_id: str) -> None:
        event = self._completed.get(job_id)
        if event:
            await event.wait()

    async def _run_queue(self) -> None:
        while True:
            job_id = await self.queue.get()
            if job_id is None:
                self.queue.task_done()
                return
            try:
                await self.gate.wait_for_background_slot()
                job = await self.repository.require_job(job_id)
                voice = await self.repository.require_voice(job.voice_id)
                await self.repository.set_job_status(job_id, TtsJobStatus.running)
                output = self.storage.output_path(job_id)
                await self.provider.synthesize(
                    job.text,
                    voice.prompt_text,
                    voice.prompt_path,
                    output,
                )
                await self.repository.set_job_status(
                    job_id,
                    TtsJobStatus.completed,
                    output_path=output,
                )
            except TtsProviderError as exc:
                await self.repository.set_job_status(
                    job_id,
                    TtsJobStatus.failed,
                    error_code=exc.code,
                    error_message=exc.public_message,
                )
            except Exception:
                logger.exception("Unexpected TTS synthesis failure for job %s", job_id)
                await self.repository.set_job_status(
                    job_id,
                    TtsJobStatus.failed,
                    error_code="synthesis_failed",
                    error_message="语音合成失败",
                )
            finally:
                if event := self._completed.get(job_id):
                    event.set()
                self.queue.task_done()

    async def close(self) -> None:
        if self.worker:
            await self.queue.put(None)
            await self.worker
        self.executor.shutdown(wait=True, cancel_futures=False)
        await self.provider.close()

    @staticmethod
    def _response(job: TtsJob) -> TtsJobResponse:
        return TtsJobResponse(
            job_id=job.id,
            voice_id=job.voice_id,
            status=job.status,
            error_code=job.error_code,
            error_message=job.error_message,
        )
