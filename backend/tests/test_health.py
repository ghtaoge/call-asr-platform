from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_runtime_status():
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Call ASR Platform"
    assert body["device"] in {"cpu", "cuda"}
    assert body["asr_provider"] == "mock"
