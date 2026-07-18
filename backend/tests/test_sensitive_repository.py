import pytest

from app.core.models import RiskLevel
from app.sensitive.repository import SensitiveWordRepository


@pytest.mark.asyncio
async def test_repository_isolates_tenants_and_uses_cursor(tmp_path):
    repository = SensitiveWordRepository(tmp_path / "sensitive.sqlite3")
    await repository.init()
    await repository.create("tenant-a", "退款", RiskLevel.high, "售后", True)
    await repository.create("tenant-b", "投诉", RiskLevel.critical, "投诉", True)
    rows, cursor, version = await repository.list_words("tenant-a", limit=1)
    assert [row.word for row in rows] == ["退款"]
    assert cursor is None
    assert version == 1
    rows, _, _ = await repository.list_words("tenant-b")
    assert [row.word for row in rows] == ["投诉"]
