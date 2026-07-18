from datetime import datetime, timezone

import jwt
from fastapi.testclient import TestClient

from app.main import create_app


def test_sensitive_admin_uses_verified_tenant_and_role(monkeypatch, tmp_path):
    monkeypatch.setenv("CALL_ASR_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(tmp_path / "app.sqlite3"))
    app = create_app()
    token = jwt.encode({"sub": "user-1", "tenant_id": "00000000-0000-0000-0000-000000000001", "roles": ["sensitive:write", "sensitive:read"], "exp": datetime.now(timezone.utc).timestamp() + 600}, "test-secret", algorithm="HS256")
    with TestClient(app) as client:
        response = client.post("/api/admin/sensitive-words", headers={"Authorization": f"Bearer {token}"}, json={"word": "绝对有效", "level": "critical", "category": "承诺"})
        assert response.status_code == 201
        listed = client.get("/api/admin/sensitive-words", headers={"Authorization": f"Bearer {token}"})
        assert listed.status_code == 200
        assert listed.json()["version"] == 1


def test_sensitive_admin_rejects_other_tenant_header(monkeypatch, tmp_path):
    monkeypatch.setenv("CALL_ASR_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("CALL_ASR_DATABASE_PATH", str(tmp_path / "app.sqlite3"))
    app = create_app()
    token = jwt.encode({"sub": "user-1", "tenant_id": "00000000-0000-0000-0000-000000000001", "roles": ["sensitive:read"], "exp": datetime.now(timezone.utc).timestamp() + 600}, "test-secret", algorithm="HS256")
    with TestClient(app) as client:
        response = client.get("/api/admin/sensitive-words", headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "00000000-0000-0000-0000-000000000002"})
        assert response.status_code == 403
