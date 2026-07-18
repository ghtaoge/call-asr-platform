from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import grpc

from app.asr_rpc.generated import asr_pb2, asr_pb2_grpc


@dataclass(frozen=True, slots=True)
class RpcBatchSegment:
    speaker: str
    start_ms: int
    end_ms: int
    text: str
    confidence: float


class AsrRpcStream:
    def __init__(self, stub: asr_pb2_grpc.AsrServiceStub, tenant_id: str, call_id: str, speaker: str) -> None:
        self.tenant_id = tenant_id
        self.call_id = call_id
        self.stream_id = call_id
        self.speaker = speaker
        self._requests: asyncio.Queue[asr_pb2.AudioFrame | None] = asyncio.Queue(maxsize=64)
        self._events: asyncio.Queue[asr_pb2.RecognitionEvent | Exception] = asyncio.Queue()
        self._call = stub.StreamRecognize(self._request_iterator())
        self._reader = asyncio.create_task(self._read_events(), name=f"asr-rpc-{call_id}")
        self._closed = False

    async def send(self, sequence: int, captured_at_ms: int, pcm: bytes, *, end: bool = False):
        if self._closed:
            raise RuntimeError("ASR RPC stream is closed")
        await self._requests.put(asr_pb2.AudioFrame(
            tenant_id=self.tenant_id,
            call_id=self.call_id,
            stream_id=self.stream_id,
            speaker=self.speaker,
            sequence=sequence,
            captured_at_ms=captured_at_ms,
            pcm_s16le=pcm,
            end_of_stream=end,
        ))
        received = []
        while True:
            event = await self._events.get()
            if isinstance(event, Exception):
                raise event
            received.append(event)
            if event.type == "audio_ack" and event.ack_sequence >= sequence:
                break
        if end:
            await self._requests.put(None)
            self._closed = True
        return received

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._requests.put(None)
            self._call.cancel()
        await asyncio.gather(self._reader, return_exceptions=True)

    async def _request_iterator(self):
        while True:
            item = await self._requests.get()
            if item is None:
                return
            yield item

    async def _read_events(self) -> None:
        try:
            async for event in self._call:
                await self._events.put(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._events.put(exc)


class AsrRpcClient:
    def __init__(self, target: str, timeout: float = 10.0) -> None:
        self.target = target
        self.timeout = timeout
        self.channel = grpc.aio.insecure_channel(
            target,
            options=(("grpc.max_receive_message_length", 100 * 1024 * 1024),),
        )
        self.stub = asr_pb2_grpc.AsrServiceStub(self.channel)

    async def start(self) -> None:
        await asyncio.wait_for(self.channel.channel_ready(), timeout=self.timeout)
        health = await self.stub.Check(asr_pb2.HealthRequest(), timeout=self.timeout)
        if health.status != "SERVING":
            raise RuntimeError(f"ASR service is not ready: {health.status}")

    def open_stream(self, tenant_id: str, call_id: str, speaker: str = "unknown") -> AsrRpcStream:
        return AsrRpcStream(self.stub, tenant_id, call_id, speaker)

    async def batch_recognize(self, tenant_id: str, job_id: str, channels: list[tuple[str, bytes]]):
        response = await self.stub.BatchRecognize(
            asr_pb2.BatchRequest(
                tenant_id=tenant_id,
                job_id=job_id,
                channels=[asr_pb2.BatchChannel(speaker=speaker, wav=wav) for speaker, wav in channels],
            ),
            timeout=max(self.timeout, 300),
        )
        return [
            RpcBatchSegment(item.speaker, item.start_ms, item.end_ms, item.text, item.confidence)
            for item in response.segments
        ]

    async def close(self) -> None:
        await self.channel.close()


class AsrRpcSyncClient:
    """Blocking adapter used from the existing JobManager worker thread."""

    def __init__(self, target: str, timeout: float = 10.0) -> None:
        self.target = target
        self.timeout = timeout
        self.channel = grpc.insecure_channel(target)
        self.stub = asr_pb2_grpc.AsrServiceStub(self.channel)

    def start(self) -> None:
        response = self.stub.Check(asr_pb2.HealthRequest(), timeout=self.timeout)
        if response.status != "SERVING":
            raise RuntimeError(f"ASR service is not ready: {response.status}")

    def batch_recognize(self, tenant_id: str, job_id: str, channels: list[tuple[str, bytes]]):
        response = self.stub.BatchRecognize(
            asr_pb2.BatchRequest(
                tenant_id=tenant_id,
                job_id=job_id,
                channels=[asr_pb2.BatchChannel(speaker=speaker, wav=wav) for speaker, wav in channels],
            ),
            timeout=max(self.timeout, 300),
        )
        return [
            RpcBatchSegment(item.speaker, item.start_ms, item.end_ms, item.text, item.confidence)
            for item in response.segments
        ]

    def close(self) -> None:
        self.channel.close()
