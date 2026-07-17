import asyncio

from app.core.inference_gate import InferenceGate


async def test_background_waits_for_realtime_to_end():
    gate = InferenceGate()
    await gate.realtime_started()
    released = asyncio.Event()

    async def wait():
        await gate.wait_for_background_slot()
        released.set()

    task = asyncio.create_task(wait())
    await asyncio.sleep(0)
    assert not released.is_set()
    await gate.realtime_ended()
    await asyncio.wait_for(task, timeout=1)
    assert released.is_set()
