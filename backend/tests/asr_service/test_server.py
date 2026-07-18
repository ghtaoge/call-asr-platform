import asyncio

import grpc
import pytest

from app.asr_rpc.generated import asr_pb2, asr_pb2_grpc
from asr_service.config import AsrServiceConfig
from asr_service.engine import EngineResult
from asr_service.scheduler import BatchScheduler
from asr_service.server import AsrService


class Engine:
    ready = True

    async def infer_batch(self, chunks):
        return [EngineResult("您好。", chunk.is_final) for chunk in chunks]


async def frames():
    for sequence in range(11):
        yield asr_pb2.AudioFrame(
            tenant_id="tenant",
            call_id="call",
            stream_id="stream",
            speaker="unknown",
            sequence=sequence,
            captured_at_ms=sequence * 20,
            pcm_s16le=b"\0\0" * 320,
            end_of_stream=sequence == 10,
        )


@pytest.mark.asyncio
async def test_stream_returns_ack_partial_and_final():
    scheduler = BatchScheduler(Engine(), tick_ms=1)
    await scheduler.start()
    server = grpc.aio.server()
    asr_pb2_grpc.add_AsrServiceServicer_to_server(
        AsrService(AsrServiceConfig(mode="realtime"), scheduler, None), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        stub = asr_pb2_grpc.AsrServiceStub(channel)
        events = [event async for event in stub.StreamRecognize(frames())]
        assert max(event.ack_sequence for event in events) == 10
        assert any(event.type == "partial_transcript" for event in events)
        final = next(event for event in events if event.is_final)
        assert final.start_ms == 0
        assert final.end_ms > final.start_ms
        health = await stub.Check(asr_pb2.HealthRequest())
        assert health.status == "SERVING"
    finally:
        await channel.close()
        await server.stop(0)
        await scheduler.close()
