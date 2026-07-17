import wave

from app.realtime.protocol import AudioFrame
from app.realtime.session import RealtimeSession
from app.realtime.streaming_asr import StreamingRecognition


PCM = b"\x01\x00" * 320


class FakeAsrSession:
    def __init__(self):
        self.calls = 0

    def feed(self, pcm, is_final=False):
        self.calls += 1
        return StreamingRecognition("您好", self.calls >= 2 or is_final)

    def reset_sentence(self):
        pass


class FakeClusterer:
    def assign(self, pcm):
        return "speaker_1"


def frame(sequence):
    return AudioFrame("s1", sequence, 1000 + sequence * 20, PCM)


def test_session_emits_partial_then_one_final_and_deduplicates(tmp_path):
    asr = FakeAsrSession()
    session = RealtimeSession("s1", asr, FakeClusterer(), tmp_path / "session.wav")
    events = []
    for sequence in range(60):
        events.extend(session.accept(frame(sequence)))

    assert [event["text"] for event in events if event["type"] == "partial_transcript"] == ["您好"]
    finals = [event for event in events if event["type"] == "final_transcript"]
    assert len(finals) == 1
    assert finals[0]["segment"]["speaker_cluster"] == "speaker_1"

    session.accept(frame(59))
    assert asr.calls == 2
    _, path = session.end()
    with wave.open(str(path), "rb") as recorded:
        assert recorded.getframerate() == 16000
        assert recorded.getnframes() == 60 * 320


def test_session_maps_clusters_to_business_roles(tmp_path):
    session = RealtimeSession("s1", FakeAsrSession(), FakeClusterer(), tmp_path / "session.wav")
    for sequence in range(60):
        session.accept(frame(sequence))
    events = session.map_speakers({"speaker_1": "sales", "speaker_2": "customer"})
    assert events[0]["type"] == "speaker_mapping_updated"
    assert session.segments[0].speaker.value == "sales"
    session.end()
