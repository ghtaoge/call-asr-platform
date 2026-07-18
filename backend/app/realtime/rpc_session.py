from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.models import Segment, Speaker
from app.postprocess.text import add_basic_punctuation
from app.realtime.audio_sink import RealtimeAudioSink
from app.realtime.protocol import AudioFrame


class RpcRealtimeSession:
    """Keeps UI/session state local while model inference runs over gRPC."""

    def __init__(self, session_id: str, stream: Any, clusterer: Any, audio_path: Path) -> None:
        self.session_id = session_id
        self.stream = stream
        self.clusterer = clusterer
        self.sink = RealtimeAudioSink(audio_path)
        self.segments: list[Segment] = []
        self.sentence_pcm: list[bytes] = []
        self.last_sequence = -1
        self.mapping: dict[str, Speaker] = {}
        self.paused = False
        self.closed = False

    async def accept(self, frame: AudioFrame) -> list[dict[str, Any]]:
        if self.closed:
            return [self._error("session_closed", "实时会话已经结束")]
        if self.paused:
            return [self._error("session_paused", "实时会话已暂停")]
        if frame.sequence <= self.last_sequence:
            return [{"type": "audio_ack", "sequence": self.last_sequence}]
        if self.last_sequence >= 0 and frame.sequence != self.last_sequence + 1:
            return [self._error("sequence_gap", "检测到音频帧缺失，请重新连接")]
        self.last_sequence = frame.sequence
        self.sink.append(frame)
        self.sentence_pcm.append(frame.payload)
        events = await self.stream.send(frame.sequence, frame.captured_at_ms, frame.payload)
        return await self._translate(events)

    async def end(self) -> tuple[list[dict[str, Any]], Path]:
        if self.closed:
            return [], self.sink.path
        sequence = self.last_sequence + 1
        captured_at = sequence * 20
        events = await self.stream.send(sequence, captured_at, b"", end=True)
        translated = await self._translate(events)
        self.closed = True
        path = self.sink.close()
        translated.append({"type": "session_ended", "session_id": self.session_id})
        return translated, path

    def pause(self):
        self.paused = True
        return [{"type": "session_paused"}]

    def resume(self):
        self.paused = False
        return [{"type": "session_resumed", "sequence": self.last_sequence}]

    def map_speakers(self, mapping: dict[str, str]):
        parsed = {cluster: Speaker(role) for cluster, role in mapping.items()}
        if set(parsed.values()) != {Speaker.sales, Speaker.customer}:
            return [self._error("invalid_speaker_mapping", "销售和客户角色必须各选择一次")]
        self.mapping = parsed
        for segment in self.segments:
            if segment.speaker_cluster in parsed:
                segment.speaker = parsed[segment.speaker_cluster]
        return [{"type": "speaker_mapping_updated", "mapping": mapping}]

    async def close(self) -> None:
        await self.stream.close()

    async def _translate(self, rpc_events) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for event in rpc_events:
            if event.type == "audio_ack":
                output.append({"type": "audio_ack", "sequence": min(event.ack_sequence, self.last_sequence)})
            elif event.type == "partial_transcript" and event.text:
                output.append({"type": "partial_transcript", "revision": len(self.segments) + 1, "text": event.text})
            elif event.type == "final_transcript" and event.text:
                cluster = self.clusterer.assign(b"".join(self.sentence_pcm))
                segment = Segment(
                    id=f"{self.session_id}_seg_{len(self.segments) + 1:04d}",
                    session_id=self.session_id,
                    speaker=self.mapping.get(cluster, Speaker.unknown),
                    speaker_cluster=cluster,
                    start_ms=max(0, event.start_ms),
                    end_ms=max(event.start_ms + 1, event.end_ms),
                    text=add_basic_punctuation(event.text),
                    language="zh",
                    target_language="zh",
                    confidence=0.92,
                )
                self.segments.append(segment)
                self.sentence_pcm.clear()
                output.append({"type": "final_transcript", "segment": segment.model_dump(mode="json")})
        return output

    @staticmethod
    def _error(code: str, message: str):
        return {"type": "error", "code": code, "message": message}
