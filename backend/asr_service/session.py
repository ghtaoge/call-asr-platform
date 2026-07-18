from __future__ import annotations

from dataclasses import dataclass, field
import time


class SequenceGapError(ValueError):
    """Raised when a stream jumps beyond the bounded reorder window."""


@dataclass(frozen=True, slots=True)
class InferenceChunk:
    call_id: str
    stream_id: str
    speaker: str
    first_sequence: int
    last_sequence: int
    captured_at_ms: int
    pcm: bytes
    is_final: bool = False

    @property
    def session_id(self) -> str:
        return f"{self.call_id}:{self.stream_id}"


@dataclass(slots=True)
class StreamingSessionState:
    call_id: str
    stream_id: str
    sample_rate: int = 16_000
    chunk_ms: int = 200
    speaker: str = "unknown"
    reorder_window: int = 32
    max_frame_bytes: int = 4096
    max_buffer_ms: int = 2000
    asr_cache: dict = field(default_factory=dict)
    vad_cache: dict = field(default_factory=dict)
    current_text: str = ""
    sentence_start_sample: int = 0
    last_activity: float = field(default_factory=time.monotonic)
    _next_sequence: int | None = None
    _pending: dict[int, tuple[int, bytes]] = field(default_factory=dict)
    _buffer: bytearray = field(default_factory=bytearray)
    _chunk_first_sequence: int | None = None
    _chunk_last_sequence: int | None = None
    _chunk_captured_at_ms: int = 0

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.chunk_ms <= 0:
            raise ValueError("sample_rate and chunk_ms must be positive")

    @property
    def chunk_bytes(self) -> int:
        return self.sample_rate * 2 * self.chunk_ms // 1000

    @property
    def buffered_ms(self) -> int:
        return len(self._buffer) * 1000 // (self.sample_rate * 2)

    def push(self, sequence: int, captured_at_ms: int, pcm: bytes) -> list[InferenceChunk]:
        if not pcm or len(pcm) % 2:
            raise ValueError("PCM frame must contain aligned 16-bit samples")
        if len(pcm) > self.max_frame_bytes:
            raise ValueError("PCM frame exceeds maximum size")
        if sequence < 0:
            raise ValueError("sequence must be non-negative")

        self.last_activity = time.monotonic()
        if self._next_sequence is None:
            self._next_sequence = sequence
        if sequence < self._next_sequence or sequence in self._pending:
            return []
        if sequence - self._next_sequence > self.reorder_window:
            raise SequenceGapError(
                f"sequence gap exceeds window: expected {self._next_sequence}, got {sequence}"
            )

        self._pending[sequence] = (captured_at_ms, pcm)
        chunks: list[InferenceChunk] = []
        while self._next_sequence in self._pending:
            current = self._next_sequence
            frame_captured_at, frame_pcm = self._pending.pop(current)
            if self._chunk_first_sequence is None:
                self._chunk_first_sequence = current
                self._chunk_captured_at_ms = frame_captured_at
            self._chunk_last_sequence = current
            self._buffer.extend(frame_pcm)
            self._next_sequence += 1
            if self.buffered_ms > self.max_buffer_ms:
                raise BufferError("streaming PCM buffer exceeded maximum duration")
            while len(self._buffer) >= self.chunk_bytes:
                chunks.append(self._take_chunk(self.chunk_bytes, is_final=False))
        return chunks

    def flush(self, *, force: bool = False) -> list[InferenceChunk]:
        if self._pending:
            raise SequenceGapError("cannot flush stream with missing frames")
        if not self._buffer:
            if not force:
                return []
            first = self._next_sequence or 0
            return [InferenceChunk(
                call_id=self.call_id,
                stream_id=self.stream_id,
                speaker=self.speaker,
                first_sequence=first,
                last_sequence=first,
                captured_at_ms=first * 20,
                pcm=b"\0\0" * (self.sample_rate * self.chunk_ms // 1000),
                is_final=True,
            )]
        return [self._take_chunk(len(self._buffer), is_final=True)]

    def _take_chunk(self, size: int, *, is_final: bool) -> InferenceChunk:
        pcm = bytes(self._buffer[:size])
        del self._buffer[:size]
        first = self._chunk_first_sequence if self._chunk_first_sequence is not None else 0
        last = self._chunk_last_sequence if self._chunk_last_sequence is not None else first
        chunk = InferenceChunk(
            call_id=self.call_id,
            stream_id=self.stream_id,
            speaker=self.speaker,
            first_sequence=first,
            last_sequence=last,
            captured_at_ms=self._chunk_captured_at_ms,
            pcm=pcm,
            is_final=is_final,
        )
        self._chunk_first_sequence = None
        self._chunk_last_sequence = None
        self._chunk_captured_at_ms = 0
        return chunk
