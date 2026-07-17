from fastapi.testclient import TestClient

from app.core.models import CallSummary, EmotionResult, QualityScore, Segment
from app.main import create_app


class FakeSessionService:
    def __init__(self, repository, sensitive_store):
        pass

    async def analyze_offline(self, audio, target_language, speaker, session_id, mode):
        segment = Segment(
            id="chunk",
            session_id=session_id,
            speaker=speaker,
            start_ms=0,
            end_ms=1000,
            text="您好。",
            emotion=EmotionResult(label="neutral", confidence=0.9, score=0),
        )
        quality = QualityScore(
            score=90,
            noise_level="low",
            silence_ratio=0,
            sales_talk_ratio=1,
            customer_talk_ratio=0,
            interruptions=0,
            negative_emotion_ratio=0,
            risk_hit_count=0,
        )
        return session_id, [segment], quality, CallSummary()

    def summarize(self, segments):
        return CallSummary(overview="实时通话已结束。")


def test_realtime_websocket_returns_final_segment(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sensitive_path = data_dir / "sensitive_words.sample.json"
    sensitive_path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(data_dir / "call_asr.sqlite3"))
    monkeypatch.setenv("CALL_ASR_SENSITIVE_WORDS_PATH", str(sensitive_path))
    monkeypatch.setattr("app.api.realtime.SessionService", FakeSessionService)
    client = TestClient(create_app())

    with client.websocket_connect("/ws/realtime/s1") as websocket:
        websocket.send_json({"type": "start_session", "speaker": "sales", "target_language": "en"})
        assert websocket.receive_json()["type"] == "session_started"
        websocket.send_json({"type": "audio_chunk", "speaker": "sales", "audio": "ZmFrZS1hdWRpbw=="})
        event = websocket.receive_json()
        assert event["type"] == "final_segment"
        assert event["segment"]["speaker"] == "sales"
        websocket.send_json({"type": "end_session"})
        while True:
            message = websocket.receive_json()
            if message["type"] == "summary_ready":
                assert message["summary"]["overview"] == "实时通话已结束。"
                break
