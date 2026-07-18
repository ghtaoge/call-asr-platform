import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.models import Segment
from app.core.inference_gate import InferenceGate
from app.jobs.manager import JobManager
from app.realtime.protocol import FrameProtocolError, decode_audio_frame
from app.realtime.session import RealtimeSession
from app.realtime.rpc_session import RpcRealtimeSession
from app.sessions.pipeline import AnalysisPipeline
from app.sessions.repository import SessionRepository


logger = logging.getLogger(__name__)


class RealtimeManager:
    def __init__(
        self,
        repository: SessionRepository,
        jobs: JobManager,
        pipeline: AnalysisPipeline,
        asr_provider: Any,
        clusterer_factory: Any,
        data_dir: Path,
        gate: InferenceGate | None = None,
        rpc_client: Any | None = None,
    ) -> None:
        self.repository = repository
        self.jobs = jobs
        self.pipeline = pipeline
        self.asr_provider = asr_provider
        self.clusterer_factory = clusterer_factory
        self.data_dir = data_dir
        self.gate = gate
        self.rpc_client = rpc_client
        self._gated_sessions: set[str] = set()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="realtime-asr")
        self.sessions: dict[str, RealtimeSession | RpcRealtimeSession] = {}

    async def start(self, session_id: str, message: dict[str, Any]) -> list[dict[str, Any]]:
        if message.get("codec") != "pcm_s16le" or message.get("sample_rate") != 16_000:
            return [self._error("unsupported_audio", "实时识别仅支持 16kHz PCM 音频")]
        existing = self.sessions.get(session_id)
        if existing and not existing.closed:
            return [{
                "type": "session_started",
                "session_id": session_id,
                "sequence": existing.last_sequence,
                "resumed": True,
            }]
        await self.repository.create_session(session_id, "realtime")
        loop = asyncio.get_running_loop()
        clusterer = self.clusterer_factory()
        await loop.run_in_executor(self.executor, clusterer.warmup)
        logger.info("Opening realtime ASR session: %s", session_id)
        logger.info("Realtime ASR session ready: %s", session_id)
        if self.gate:
            await self.gate.realtime_started()
            self._gated_sessions.add(session_id)
        if self.rpc_client:
            session = RpcRealtimeSession(
                session_id,
                self.rpc_client.open_stream("default", session_id),
                clusterer,
                self.data_dir / session_id / "source.wav",
            )
        else:
            asr_session = await loop.run_in_executor(self.executor, self.asr_provider.open_session)
            session = RealtimeSession(
                session_id,
                asr_session,
                clusterer,
                self.data_dir / session_id / "source.wav",
            )
        self.sessions[session_id] = session
        return [{
            "type": "session_started",
            "session_id": session_id,
            "sequence": -1,
            "resumed": False,
        }]

    async def accept(self, session_id: str, raw: bytes) -> list[dict[str, Any]]:
        try:
            session = self._require(session_id)
        except RuntimeError as exc:
            return [self._error("session_not_started", str(exc))]
        try:
            frame = decode_audio_frame(session_id, raw)
        except FrameProtocolError as exc:
            return [self._error("invalid_audio_frame", str(exc))]
        if isinstance(session, RpcRealtimeSession):
            events = await session.accept(frame)
        else:
            loop = asyncio.get_running_loop()
            events = await loop.run_in_executor(self.executor, session.accept, frame)
        return await self._persist_final_events(session, events)

    async def control(
        self,
        session_id: str,
        message: dict[str, Any],
    ) -> list[dict[str, Any]]:
        event_type = message.get("type")
        if event_type == "start_session":
            return await self.start(session_id, message)
        try:
            session = self._require(session_id)
        except RuntimeError as exc:
            return [self._error("session_not_started", str(exc))]
        if event_type == "pause_session":
            return session.pause()
        if event_type == "resume_session":
            return session.resume()
        if event_type == "resume_session_connection":
            return [{
                "type": "session_started",
                "session_id": session_id,
                "sequence": session.last_sequence,
                "resumed": True,
            }]
        if event_type == "map_speakers":
            events = session.map_speakers(message.get("mapping", {}))
            if events[0]["type"] != "error":
                await self.repository.save_segments(session_id, session.segments)
            return events
        if event_type == "end_session":
            try:
                if isinstance(session, RpcRealtimeSession):
                    events, path = await session.end()
                else:
                    loop = asyncio.get_running_loop()
                    events, path = await loop.run_in_executor(self.executor, session.end)
                events = await self._persist_final_events(session, events)
                await self.repository.save_segments(session_id, session.segments)
                created = await self.jobs.create_realtime_analysis(
                    session_id,
                    path.read_bytes(),
                    session.segments,
                )
                for event in events:
                    if event["type"] == "session_ended":
                        event["job_id"] = created.job_id
                return events
            finally:
                if self.gate and session_id in self._gated_sessions:
                    await self.gate.realtime_ended()
                    self._gated_sessions.remove(session_id)
        return [self._error("unsupported_event", "不支持的实时会话操作")]

    async def _persist_final_events(
        self,
        session: RealtimeSession | RpcRealtimeSession,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        final_ids = {
            event["segment"]["id"]
            for event in events
            if event.get("type") == "final_transcript"
        }
        if not final_ids:
            return events
        segments = [segment for segment in session.segments if segment.id in final_ids]
        loop = asyncio.get_running_loop()
        risks = await loop.run_in_executor(self.executor, self.pipeline.scan_risks, segments)
        for segment in segments:
            risk = risks[segment.id]
            segment.sensitive_hits = risk.sensitive_hits
            segment.compliance_hits = risk.compliance_hits
        await self.repository.save_segments(session.session_id, session.segments)
        all_risks = await self.repository.get_risks(session.session_id)
        all_risks.update(risks)
        await self.repository.save_risks(session.session_id, all_risks)
        for event in events:
            if event.get("type") == "final_transcript":
                segment = next(item for item in segments if item.id == event["segment"]["id"])
                event["segment"] = segment.model_dump(mode="json")
        events.extend({
            "type": "risk_update",
            "segment_id": segment.id,
            "sensitive_hits": [hit.model_dump(mode="json") for hit in segment.sensitive_hits],
            "compliance_hits": [hit.model_dump(mode="json") for hit in segment.compliance_hits],
        } for segment in segments)
        return events

    async def close(self) -> None:
        for session in self.sessions.values():
            if not session.closed:
                if isinstance(session, RpcRealtimeSession):
                    await session.end()
                else:
                    session.end()
            if isinstance(session, RpcRealtimeSession):
                await session.close()
        if self.gate:
            for session_id in list(self._gated_sessions):
                await self.gate.realtime_ended()
                self._gated_sessions.remove(session_id)
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _require(self, session_id: str) -> RealtimeSession | RpcRealtimeSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise RuntimeError("实时会话尚未开始") from exc

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"type": "error", "code": code, "message": message}
