from datetime import UTC, datetime
from threading import Lock

from app.tts.models import TtsHealthResponse, TtsHealthStatus


class TtsHealthCache:
    """Thread-safe snapshot shared by the queue, API and UI status polling."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._value = TtsHealthResponse(
            status=TtsHealthStatus.starting,
            message="语音合成模型正在启动",
            checked_at=datetime.now(UTC),
        )

    def snapshot(self) -> TtsHealthResponse:
        with self._lock:
            return self._value.model_copy(deep=True)

    def mark_ready(self, model: str, queue_depth: int) -> None:
        status = TtsHealthStatus.busy if queue_depth else TtsHealthStatus.ready
        message = "任务较多，已进入队列" if queue_depth else "语音合成服务可用"
        with self._lock:
            self._value = TtsHealthResponse(
                status=status,
                model=model,
                queue_depth=max(queue_depth, 0),
                message=message,
                checked_at=datetime.now(UTC),
            )

    def mark_unavailable(
        self,
        code: str,
        message: str,
        *,
        fallback_available: bool = False,
    ) -> None:
        with self._lock:
            self._value = TtsHealthResponse(
                status=TtsHealthStatus.unavailable,
                error_code=code,
                fallback_available=fallback_available,
                message=message,
                checked_at=datetime.now(UTC),
            )
