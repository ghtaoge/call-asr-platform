from __future__ import annotations

import argparse
import asyncio
import logging
from typing import AsyncIterator

import grpc

from app.asr.model_registry import ModelRegistry
from app.asr.sensevoice_provider import SenseVoiceProvider
from app.asr_rpc.generated import asr_pb2, asr_pb2_grpc
from app.realtime.streaming_asr import FunAsrStreamingProvider
from asr_service.batch_engine import BatchInput, FunAsrBatchEngine
from asr_service.config import AsrServiceConfig
from asr_service.engine import EngineResult, FunAsrStreamingEngine
from asr_service.scheduler import BatchScheduler
from asr_service.session import SequenceGapError, StreamingSessionState


logger = logging.getLogger(__name__)


class AsrService(asr_pb2_grpc.AsrServiceServicer):
    def __init__(
        self,
        config: AsrServiceConfig,
        scheduler: BatchScheduler | None,
        batch_engine: FunAsrBatchEngine | None,
    ) -> None:
        self.config = config
        self.scheduler = scheduler
        self.batch_engine = batch_engine

    async def StreamRecognize(self, request_iterator, context) -> AsyncIterator[asr_pb2.RecognitionEvent]:
        if self.scheduler is None:
            await context.abort(grpc.StatusCode.UNIMPLEMENTED, "realtime ASR is disabled")
        state: StreamingSessionState | None = None
        identity: tuple[str, str, str, str] | None = None
        sentence_start_ms = 0
        try:
            async for frame in request_iterator:
                incoming_identity = (frame.tenant_id, frame.call_id, frame.stream_id, frame.speaker)
                if identity is None:
                    identity = incoming_identity
                    state = StreamingSessionState(
                        frame.call_id,
                        frame.stream_id,
                        chunk_ms=self.config.chunk_ms,
                        speaker=frame.speaker or "unknown",
                    )
                elif identity != incoming_identity:
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "stream identity changed")
                assert state is not None

                chunks = state.push(frame.sequence, frame.captured_at_ms, frame.pcm_s16le) if frame.pcm_s16le else []
                if frame.end_of_stream:
                    chunks.extend(state.flush(force=True))
                for chunk in chunks:
                    try:
                        future = await self.scheduler.submit(chunk)
                    except asyncio.QueueFull:
                        await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "asr_queue_full")
                    result: EngineResult = await future
                    end_ms = max(sentence_start_ms + 1, chunk.captured_at_ms + len(chunk.pcm) * 1000 // 32_000)
                    event_type = "final_transcript" if result.endpoint else "partial_transcript"
                    yield asr_pb2.RecognitionEvent(
                        call_id=frame.call_id,
                        stream_id=frame.stream_id,
                        type=event_type,
                        ack_sequence=chunk.last_sequence,
                        start_ms=sentence_start_ms,
                        end_ms=end_ms,
                        text=result.text,
                        is_final=result.endpoint,
                    )
                    if result.endpoint:
                        sentence_start_ms = end_ms
                yield asr_pb2.RecognitionEvent(
                    call_id=frame.call_id,
                    stream_id=frame.stream_id,
                    type="audio_ack",
                    ack_sequence=frame.sequence,
                )
                if frame.end_of_stream:
                    return
        except (ValueError, BufferError, SequenceGapError) as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))

    async def BatchRecognize(self, request, context):
        if self.batch_engine is None:
            await context.abort(grpc.StatusCode.UNIMPLEMENTED, "batch ASR is disabled")
        total_bytes = sum(len(channel.wav) for channel in request.channels)
        if total_bytes > self.config.max_batch_audio_bytes:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "batch_audio_too_large")
        try:
            inputs = [BatchInput(channel.speaker, channel.wav) for channel in request.channels]
            segments = await self.batch_engine.recognize(request.job_id, inputs)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        return asr_pb2.BatchResponse(
            segments=[
                asr_pb2.BatchSegment(
                    speaker=item.speaker,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                    text=item.text,
                    confidence=item.confidence,
                )
                for item in segments
            ],
            model_version=self.batch_engine.model_version,
        )

    async def Check(self, request, context):
        realtime_ready = self.scheduler is None or getattr(self.scheduler.engine, "ready", False)
        batch_ready = self.batch_engine is None or self.batch_engine.ready
        return asr_pb2.HealthResponse(
            status="SERVING" if realtime_ready and batch_ready else "NOT_SERVING",
            model_version=self.config.model_version,
            queue_depth=self.scheduler.queue_depth if self.scheduler else 0,
            artifact_checksum=self.config.artifact_checksum,
        )


async def build_service(config: AsrServiceConfig) -> tuple[AsrService, BatchScheduler | None]:
    registry = ModelRegistry(device=config.device)
    scheduler = None
    batch_engine = None
    if config.mode in {"all", "realtime"}:
        stream_engine = FunAsrStreamingEngine(
            FunAsrStreamingProvider(registry.streaming_asr, registry.streaming_vad)
        )
        await stream_engine.warmup()
        scheduler = BatchScheduler(
            stream_engine,
            max_batch=config.max_batch,
            tick_ms=config.tick_ms,
            max_wait_ms=config.max_wait_ms,
            max_queue=config.max_queue,
        )
        await scheduler.start()
    if config.mode in {"all", "batch"}:
        batch_engine = FunAsrBatchEngine(
            SenseVoiceProvider(model_loader=registry.sensevoice),
            config.model_version,
        )
        await batch_engine.warmup()
    return AsrService(config, scheduler, batch_engine), scheduler


async def serve(config: AsrServiceConfig) -> None:
    service, scheduler = await build_service(config)
    server = grpc.aio.server(options=(("grpc.max_receive_message_length", config.max_batch_audio_bytes),))
    asr_pb2_grpc.add_AsrServiceServicer_to_server(service, server)
    server.add_insecure_port(f"{config.host}:{config.port}")
    await server.start()
    logger.info("ASR %s service listening on %s:%d", config.mode, config.host, config.port)
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(grace=10)
        if scheduler:
            await scheduler.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("all", "realtime", "batch"))
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    config = AsrServiceConfig.from_env()
    if args.mode or args.port:
        config = AsrServiceConfig(**{
            **{field: getattr(config, field) for field in config.__dataclass_fields__},
            **({"mode": args.mode} if args.mode else {}),
            **({"port": args.port} if args.port else {}),
        })
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(config))


if __name__ == "__main__":
    main()
