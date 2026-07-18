from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.asr.sensevoice_provider import SenseVoiceProvider
from app.core.models import Speaker


@dataclass(frozen=True, slots=True)
class BatchInput:
    speaker: str
    wav: bytes


@dataclass(frozen=True, slots=True)
class BatchResultSegment:
    speaker: str
    start_ms: int
    end_ms: int
    text: str
    confidence: float


class FunAsrBatchEngine:
    def __init__(self, provider: SenseVoiceProvider, model_version: str) -> None:
        self.provider = provider
        self.model_version = model_version
        self.ready = False

    async def warmup(self) -> None:
        # Loading the model is the expensive readiness boundary. A real speech
        # fixture is used by the production benchmark rather than hidden here.
        await asyncio.to_thread(self.provider._get_model)
        self.ready = True

    async def recognize(self, job_id: str, channels: list[BatchInput]) -> list[BatchResultSegment]:
        return await asyncio.to_thread(self._recognize_sync, job_id, channels)

    def _recognize_sync(self, job_id: str, channels: list[BatchInput]) -> list[BatchResultSegment]:
        output: list[BatchResultSegment] = []
        for channel in channels:
            speaker = Speaker(channel.speaker)
            segments = self.provider.transcribe(channel.wav, job_id, speaker)
            output.extend(
                BatchResultSegment(
                    speaker=segment.speaker.value,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    confidence=segment.confidence,
                )
                for segment in segments
            )
        return sorted(output, key=lambda segment: (segment.start_ms, segment.end_ms, segment.speaker))
