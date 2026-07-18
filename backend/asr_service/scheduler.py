from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import time
from typing import Any, Protocol

from prometheus_client import Counter, Gauge, Histogram

from asr_service.session import InferenceChunk


QUEUE_DEPTH = Gauge("asr_scheduler_queue_depth", "Queued realtime ASR chunks")
BATCH_SIZE = Histogram("asr_scheduler_batch_size", "Realtime ASR inference batch size")
INFERENCE_SECONDS = Histogram("asr_scheduler_inference_seconds", "Realtime batch inference time")
REJECTED = Counter("asr_scheduler_rejected_total", "Chunks rejected because the queue is full")
DEADLINE_MISSES = Counter("asr_scheduler_deadline_misses_total", "Chunks inferred after max wait")


class BatchEngine(Protocol):
    async def infer_batch(self, chunks: list[InferenceChunk]) -> list[Any]: ...


@dataclass(slots=True)
class _QueuedChunk:
    chunk: InferenceChunk
    enqueued_at_ms: float
    future: asyncio.Future[Any]


class BatchScheduler:
    """Bounded fair scheduler that emits at most one chunk per session per batch."""

    def __init__(
        self,
        engine: BatchEngine,
        *,
        max_batch: int = 16,
        tick_ms: int = 40,
        max_wait_ms: int = 120,
        max_queue: int = 2048,
        clock: callable | None = None,
    ) -> None:
        self.engine = engine
        self.max_batch = max_batch
        self.tick_ms = tick_ms
        self.max_wait_ms = max_wait_ms
        self.max_queue = max_queue
        self.clock = clock or (lambda: time.monotonic() * 1000)
        self._queue: deque[_QueuedChunk] = deque()
        self._lock = asyncio.Lock()
        self._runner: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    async def start(self) -> None:
        if self._runner is None:
            self._runner = asyncio.create_task(self._run(), name="asr-batch-scheduler")

    async def submit(self, chunk: InferenceChunk) -> asyncio.Future[Any]:
        async with self._lock:
            if self._closed:
                raise RuntimeError("ASR scheduler is closed")
            if len(self._queue) >= self.max_queue:
                REJECTED.inc()
                raise asyncio.QueueFull
            future = asyncio.get_running_loop().create_future()
            self._queue.append(_QueuedChunk(chunk, self.clock(), future))
            QUEUE_DEPTH.set(len(self._queue))
            return future

    async def tick(self) -> None:
        async with self._lock:
            if not self._queue:
                return
            batch: list[_QueuedChunk] = []
            deferred: deque[_QueuedChunk] = deque()
            sessions: set[str] = set()
            while self._queue and len(batch) < self.max_batch:
                item = self._queue.popleft()
                if item.future.cancelled():
                    continue
                if item.chunk.session_id in sessions:
                    deferred.append(item)
                    continue
                sessions.add(item.chunk.session_id)
                batch.append(item)
            deferred.extend(self._queue)
            self._queue = deferred
            QUEUE_DEPTH.set(len(self._queue))

        if not batch:
            return
        now = self.clock()
        DEADLINE_MISSES.inc(sum(1 for item in batch if now - item.enqueued_at_ms > self.max_wait_ms))
        BATCH_SIZE.observe(len(batch))
        started = time.perf_counter()
        try:
            results = await self.engine.infer_batch([item.chunk for item in batch])
            if len(results) != len(batch):
                raise RuntimeError("ASR engine returned a mismatched batch size")
            for item, result in zip(batch, results, strict=True):
                if not item.future.done():
                    item.future.set_result(result)
        except Exception as exc:
            for item in batch:
                if not item.future.done():
                    item.future.set_exception(exc)
        finally:
            INFERENCE_SECONDS.observe(time.perf_counter() - started)

    async def close(self) -> None:
        self._closed = True
        if self._runner is not None:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
            self._runner = None
        while self._queue:
            item = self._queue.popleft()
            if not item.future.done():
                item.future.set_exception(RuntimeError("ASR scheduler closed"))
        QUEUE_DEPTH.set(0)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.tick_ms / 1000)
            await self.tick()
