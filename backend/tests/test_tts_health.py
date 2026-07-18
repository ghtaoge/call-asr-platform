from app.tts.health import TtsHealthCache
from app.tts.models import TtsHealthStatus


def test_health_cache_tracks_ready_busy_and_unavailable_states():
    cache = TtsHealthCache()
    assert cache.snapshot().status == TtsHealthStatus.starting

    cache.mark_ready("Fun-CosyVoice3-0.5B-2512", queue_depth=3)
    busy = cache.snapshot()
    assert busy.status == TtsHealthStatus.busy
    assert busy.queue_depth == 3

    cache.mark_unavailable("worker_connection_failed", "语音合成服务暂不可用")
    unavailable = cache.snapshot()
    assert unavailable.status == TtsHealthStatus.unavailable
    assert unavailable.error_code == "worker_connection_failed"
