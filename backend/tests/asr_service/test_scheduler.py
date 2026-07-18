import asyncio

import pytest

from asr_service.scheduler import BatchScheduler
from asr_service.session import InferenceChunk


class Engine:
    def __init__(self):
        self.batches: list[list[str]] = []

    async def infer_batch(self, chunks):
        self.batches.append([chunk.session_id for chunk in chunks])
        return [chunk.last_sequence for chunk in chunks]


def chunk(stream: str, sequence: int = 0) -> InferenceChunk:
    return InferenceChunk("call", stream, "unknown", sequence, sequence, 0, b"\0\0")


@pytest.mark.asyncio
async def test_scheduler_batches_different_sessions_and_completes_futures():
    engine = Engine()
    scheduler = BatchScheduler(engine, max_batch=16)
    first = await scheduler.submit(chunk("a", 1))
    second = await scheduler.submit(chunk("b", 2))
    await scheduler.tick()
    assert engine.batches == [["call:a", "call:b"]]
    assert await first == 1
    assert await second == 2


@pytest.mark.asyncio
async def test_scheduler_does_not_batch_same_session_twice():
    engine = Engine()
    scheduler = BatchScheduler(engine, max_batch=16)
    first = await scheduler.submit(chunk("a", 1))
    second = await scheduler.submit(chunk("a", 2))
    await scheduler.tick()
    assert await first == 1
    assert not second.done()
    await scheduler.tick()
    assert await second == 2


@pytest.mark.asyncio
async def test_scheduler_rejects_queue_overflow():
    scheduler = BatchScheduler(Engine(), max_queue=1)
    await scheduler.submit(chunk("a"))
    with pytest.raises(asyncio.QueueFull):
        await scheduler.submit(chunk("b"))
    await scheduler.close()
