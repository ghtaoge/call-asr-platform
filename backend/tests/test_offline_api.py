from fastapi.testclient import TestClient

from app.main import create_app


def test_offline_upload_returns_segments_and_summary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sensitive_words.sample.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(data_dir / "call_asr.sqlite3"))
    monkeypatch.setenv("CALL_ASR_SENSITIVE_WORDS_PATH", str(data_dir / "sensitive_words.sample.json"))
    client = TestClient(create_app())

    response = client.post(
        "/api/sessions/offline",
        files={"file": ("call.wav", b"fake-audio", "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["segments"][0]["text"]
    assert "quality" in body
    assert "summary" in body
