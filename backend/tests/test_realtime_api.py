from fastapi.testclient import TestClient

from app.main import create_app


def test_realtime_websocket_returns_final_segment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sensitive_words.sample.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(data_dir / "call_asr.sqlite3"))
    monkeypatch.setenv("CALL_ASR_SENSITIVE_WORDS_PATH", str(data_dir / "sensitive_words.sample.json"))
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
                assert "summary" in message
                break
