import pytest

from asr_service.session import SequenceGapError, StreamingSessionState


def frame() -> bytes:
    return b"\0\0" * 320


def test_session_aggregates_ten_20ms_frames_into_200ms_chunk():
    session = StreamingSessionState("call", "stream", sample_rate=16_000, chunk_ms=200)
    chunks = []
    for sequence in range(10):
        chunks.extend(session.push(sequence, sequence * 20, frame()))
    assert len(chunks) == 1
    assert chunks[0].first_sequence == 0
    assert chunks[0].last_sequence == 9
    assert len(chunks[0].pcm) == 6400


def test_session_reorders_small_gap_and_rejects_large_gap():
    session = StreamingSessionState("call", "stream", reorder_window=8)
    session.push(0, 0, frame())
    assert session.push(2, 40, frame()) == []
    assert session.push(1, 20, frame()) == []
    assert session.push(1, 20, frame()) == []
    with pytest.raises(SequenceGapError):
        session.push(20, 400, frame())


def test_session_flushes_short_final_chunk():
    session = StreamingSessionState("call", "stream")
    session.push(0, 0, frame())
    [chunk] = session.flush()
    assert chunk.is_final
    assert chunk.pcm == frame()
