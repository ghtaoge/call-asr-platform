import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TtsDelivery:
    message_id: str
    job_id: str


class TtsQueue(Protocol):
    async def start(self) -> None: ...
    async def enqueue(self, job_id: str) -> None: ...
    async def next(self, timeout_ms: int = 1000) -> TtsDelivery | None: ...
    async def ack(self, message_id: str) -> None: ...
    async def depth(self) -> int: ...
    async def close(self) -> None: ...


class InMemoryTtsQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[TtsDelivery] = asyncio.Queue()
        self._sequence = 0

    async def start(self) -> None:
        return None

    async def enqueue(self, job_id: str) -> None:
        self._sequence += 1
        await self._queue.put(TtsDelivery(str(self._sequence), job_id))

    async def next(self, timeout_ms: int = 1000) -> TtsDelivery | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout_ms / 1000)
        except asyncio.TimeoutError:
            return None

    async def ack(self, message_id: str) -> None:
        self._queue.task_done()

    async def depth(self) -> int:
        return self._queue.qsize()

    async def close(self) -> None:
        return None


class RedisTtsQueue:
    def __init__(
        self,
        redis,
        stream: str = "tts-jobs",
        group: str = "tts-workers",
        consumer: str = "backend",
    ) -> None:
        self.redis = redis
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self._started = False

    @classmethod
    def from_url(cls, url: str) -> "RedisTtsQueue":
        from redis.asyncio import Redis

        return cls(Redis.from_url(url, decode_responses=True))

    async def start(self) -> None:
        from redis.exceptions import ResponseError

        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._started = True

    async def enqueue(self, job_id: str) -> None:
        await self.redis.xadd(self.stream, {"job_id": job_id})

    async def next(self, timeout_ms: int = 1000) -> TtsDelivery | None:
        reclaimed = await self._reclaim()
        if reclaimed:
            return reclaimed
        rows = await self.redis.xreadgroup(
            self.group,
            self.consumer,
            {self.stream: ">"},
            count=1,
            block=timeout_ms,
        )
        if not rows:
            return None
        message_id, fields = rows[0][1][0]
        return TtsDelivery(str(message_id), str(fields["job_id"]))

    async def _reclaim(self) -> TtsDelivery | None:
        result = await self.redis.xautoclaim(
            self.stream,
            self.group,
            self.consumer,
            min_idle_time=60_000,
            start_id="0-0",
            count=1,
        )
        messages = result[1] if result and len(result) > 1 else []
        if not messages:
            return None
        message_id, fields = messages[0]
        return TtsDelivery(str(message_id), str(fields["job_id"]))

    async def ack(self, message_id: str) -> None:
        await self.redis.xack(self.stream, self.group, message_id)
        await self.redis.xdel(self.stream, message_id)

    async def depth(self) -> int:
        return int(await self.redis.xlen(self.stream))

    async def close(self) -> None:
        await self.redis.aclose()
