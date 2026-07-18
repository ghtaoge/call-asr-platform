from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class AsrServiceConfig:
    mode: str = "all"
    host: str = "0.0.0.0"
    port: int = 50051
    device: str = "cuda"
    chunk_ms: int = 200
    max_batch: int = 16
    tick_ms: int = 40
    max_wait_ms: int = 120
    max_queue: int = 2048
    max_batch_audio_bytes: int = 100 * 1024 * 1024
    model_version: str = "funasr-paraformer"
    artifact_checksum: str = "runtime-modelscope-cache"

    @classmethod
    def from_env(cls) -> "AsrServiceConfig":
        return cls(
            mode=os.getenv("ASR_MODE", "all"),
            host=os.getenv("ASR_HOST", "0.0.0.0"),
            port=int(os.getenv("ASR_PORT", "50051")),
            device=os.getenv("ASR_DEVICE", "cuda"),
            chunk_ms=int(os.getenv("ASR_CHUNK_MS", "200")),
            max_batch=int(os.getenv("ASR_MAX_BATCH", "16")),
            tick_ms=int(os.getenv("ASR_TICK_MS", "40")),
            max_wait_ms=int(os.getenv("ASR_MAX_WAIT_MS", "120")),
            max_queue=int(os.getenv("ASR_MAX_QUEUE", "2048")),
            max_batch_audio_bytes=int(os.getenv("ASR_MAX_BATCH_AUDIO_BYTES", str(100 * 1024 * 1024))),
            model_version=os.getenv("ASR_MODEL_VERSION", "funasr-paraformer"),
            artifact_checksum=os.getenv("ASR_ARTIFACT_CHECKSUM", "runtime-modelscope-cache"),
        )
