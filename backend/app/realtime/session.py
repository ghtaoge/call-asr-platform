from pathlib import Path
from typing import Any

from app.core.models import Segment, Speaker
from app.postprocess.text import add_basic_punctuation
from app.realtime.audio_sink import RealtimeAudioSink
from app.realtime.protocol import AudioFrame


FRAMES_PER_ASR_CHUNK = 30


class RealtimeSession:
    def __init__(self, session_id: str, asr_session: Any, clusterer: Any, audio_path: Path) -> None:
        self.session_id = session_id
        self.asr = asr_session
        self.clusterer = clusterer
        self.sink = RealtimeAudioSink(audio_path)
        self.pending: list[bytes] = []
        self.sentence_pcm: list[bytes] = []
        self.segments: list[Segment] = []
        self.last_sequence = -1
        self.first_capture_ms: int | None = None
        self.sentence_start_ms = 0
        self.revision = 0
        self.partial_text = ""
        self.paused = False
        self.closed = False
        self.mapping: dict[str, Speaker] = {}

    def accept(self, frame: AudioFrame) -> list[dict[str, Any]]:
        if self.closed:
            return [self._error("session_closed", "实时会话已经结束")]
        if self.paused:
            return [self._error("session_paused", "实时会话已暂停")]
        if frame.sequence <= self.last_sequence:
            return [self._ack()]
        if self.last_sequence >= 0 and frame.sequence != self.last_sequence + 1:
            return [self._error("sequence_gap", "检测到音频帧缺失，请重新连接")]
        if self.first_capture_ms is None:
            self.first_capture_ms = frame.captured_at_ms
            self.sentence_start_ms = 0
        self.last_sequence = frame.sequence
        self.sink.append(frame)
        self.pending.append(frame.payload)
        self.sentence_pcm.append(frame.payload)
        events: list[dict[str, Any]] = []
        if len(self.pending) >= FRAMES_PER_ASR_CHUNK:
            events.extend(self._recognize(b"".join(self.pending), is_final=False))
            self.pending.clear()
        events.append(self._ack())
        return events

    def pause(self) -> list[dict[str, Any]]:
        self.paused = True
        return [{"type": "session_paused"}]

    def resume(self) -> list[dict[str, Any]]:
        self.paused = False
        return [{"type": "session_resumed", "sequence": self.last_sequence}]

    def map_speakers(self, mapping: dict[str, str]) -> list[dict[str, Any]]:
        parsed = {cluster: Speaker(role) for cluster, role in mapping.items()}
        if set(parsed.values()) != {Speaker.sales, Speaker.customer}:
            return [self._error("invalid_speaker_mapping", "销售和客户角色必须各选择一次")]
        self.mapping = parsed
        for segment in self.segments:
            if segment.speaker_cluster in parsed:
                segment.speaker = parsed[segment.speaker_cluster]
        return [{"type": "speaker_mapping_updated", "mapping": mapping}]

    def end(self) -> tuple[list[dict[str, Any]], Path]:
        if self.closed:
            return [], self.sink.path
        events = self._recognize(b"".join(self.pending) + b"\x00" * 6400, is_final=True)
        self.pending.clear()
        self.closed = True
        path = self.sink.close()
        events.append({"type": "session_ended", "session_id": self.session_id})
        return events, path

    def _recognize(self, pcm16: bytes, is_final: bool) -> list[dict[str, Any]]:
        if not pcm16:
            return []
        result = self.asr.feed(pcm16, is_final=is_final)
        events: list[dict[str, Any]] = []
        if result.text and result.text != self.partial_text:
            self.partial_text = result.text
            self.revision += 1
            events.append({
                "type": "partial_transcript",
                "revision": self.revision,
                "text": result.text,
            })
        if result.endpoint and result.text:
            text = add_basic_punctuation(result.text)
            cluster = self.clusterer.assign(b"".join(self.sentence_pcm))
            end_ms = max(self.sentence_start_ms + 20, (self.last_sequence + 1) * 20)
            segment = Segment(
                id=f"{self.session_id}_seg_{len(self.segments) + 1:04d}",
                session_id=self.session_id,
                speaker=self.mapping.get(cluster, Speaker.unknown),
                speaker_cluster=cluster,
                start_ms=self.sentence_start_ms,
                end_ms=end_ms,
                text=text,
                language="zh",
                target_language="zh",
            )
            self.segments.append(segment)
            events.append({
                "type": "final_transcript",
                "segment": segment.model_dump(mode="json"),
            })
            self.sentence_start_ms = end_ms
            self.sentence_pcm.clear()
            self.partial_text = ""
            self.asr.reset_sentence()
        return events

    def _ack(self) -> dict[str, Any]:
        return {"type": "audio_ack", "sequence": self.last_sequence}

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"type": "error", "code": code, "message": message}
