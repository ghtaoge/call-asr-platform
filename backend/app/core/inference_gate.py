import asyncio


class InferenceGate:
    def __init__(self) -> None:
        self._active_realtime = 0
        self._condition = asyncio.Condition()

    @property
    def active_realtime(self) -> int:
        return self._active_realtime

    async def realtime_started(self) -> None:
        async with self._condition:
            self._active_realtime += 1

    async def realtime_ended(self) -> None:
        async with self._condition:
            if self._active_realtime <= 0:
                raise RuntimeError("realtime inference counter is already zero")
            self._active_realtime -= 1
            self._condition.notify_all()

    async def wait_for_background_slot(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._active_realtime == 0)
