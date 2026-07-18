import fakeredis.aioredis

from app.tts.queue import InMemoryTtsQueue, RedisTtsQueue


async def test_in_memory_queue_delivers_and_acknowledges():
    queue = InMemoryTtsQueue()
    await queue.start()
    await queue.enqueue("tts_1")
    delivery = await queue.next(timeout_ms=10)
    assert delivery is not None
    assert delivery.job_id == "tts_1"
    await queue.ack(delivery.message_id)
    assert await queue.depth() == 0


async def test_redis_queue_delivers_and_acknowledges():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    queue = RedisTtsQueue(redis, consumer="test-worker")
    await queue.start()
    await queue.enqueue("tts_2")
    delivery = await queue.next(timeout_ms=10)
    assert delivery is not None
    assert delivery.job_id == "tts_2"
    await queue.ack(delivery.message_id)
    assert await queue.depth() == 0
    await queue.close()
