from fastapi.testclient import TestClient

from app.main import create_app


def test_url_analysis_route_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sensitive_words.sample.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(data_dir / "call_asr.sqlite3"))
    monkeypatch.setenv("CALL_ASR_SENSITIVE_WORDS_PATH", str(data_dir / "sensitive_words.sample.json"))
    client = TestClient(create_app())

    response = client.post(
        "/api/sessions/url",
        json={"audio_url": "https://example.com/test.wav"},
    )

    # Route exists — not 404. May return 502 (can't actually download) but must not 404.
    assert response.status_code != 404


def test_url_analysis_rejects_invalid_url_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sensitive_words.sample.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(data_dir / "call_asr.sqlite3"))
    monkeypatch.setenv("CALL_ASR_SENSITIVE_WORDS_PATH", str(data_dir / "sensitive_words.sample.json"))
    client = TestClient(create_app())

    response = client.post(
        "/api/sessions/url",
        json={"audio_url": "ftp://example.com/audio.wav"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "音频 URL 格式不合法"
