from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
from typing import Any

from app.realtime.streaming_asr import FunAsrStreamingProvider
from asr_service.session import InferenceChunk


class ModelArtifactError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EngineResult:
    text: str
    endpoint: bool


def validate_manifest(path: Path) -> dict[str, Any]:
    """Validate every artifact before any runtime creates a GPU session."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent.resolve()
    for item in manifest.get("files", []):
        relative = Path(item["path"])
        artifact = (base / relative).resolve()
        if base not in artifact.parents or not artifact.is_file():
            raise ModelArtifactError(f"missing model artifact: {relative}")
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if checksum != item.get("sha256"):
            raise ModelArtifactError(f"model artifact checksum mismatch: {relative}")
    return manifest


class FunAsrStreamingEngine:
    """Service-owned FunASR sessions behind the scheduler engine boundary.

    The scheduler is intentionally independent of this adapter so an ONNX/TensorRT
    batch runtime can replace it without changing gRPC or browser contracts.
    """

    def __init__(self, provider: FunAsrStreamingProvider) -> None:
        self.provider = provider
        self.sessions: dict[str, Any] = {}
        self.ready = False

    async def warmup(self) -> None:
        await asyncio.to_thread(self._warmup_sync)
        self.ready = True

    def _warmup_sync(self) -> None:
        session = self.provider.open_session()
        session.feed(b"\0\0" * 3200, is_final=True)

    async def infer_batch(self, chunks: list[InferenceChunk]) -> list[EngineResult]:
        return await asyncio.to_thread(self._infer_sync, chunks)

    def _infer_sync(self, chunks: list[InferenceChunk]) -> list[EngineResult]:
        results: list[EngineResult] = []
        for chunk in chunks:
            session = self.sessions.get(chunk.session_id)
            if session is None:
                session = self.provider.open_session()
                self.sessions[chunk.session_id] = session
            recognition = session.feed(chunk.pcm, is_final=chunk.is_final)
            results.append(EngineResult(recognition.text, recognition.endpoint))
            if recognition.endpoint:
                session.reset_sentence()
            if chunk.is_final:
                self.sessions.pop(chunk.session_id, None)
        return results
