import pytest

from app.pbx.models import PbxCallStart, PbxCallStatus
from app.pbx.repository import PbxCallRepository


@pytest.mark.asyncio
async def test_pbx_call_start_is_idempotent_and_tenant_scoped(tmp_path):
    repository = PbxCallRepository(tmp_path / "calls.sqlite3")
    await repository.init()
    payload = PbxCallStart(source_session_id="siprec-1", trunk_id="trunk-a", role_pending=True)
    first = await repository.start("tenant-a", payload)
    second = await repository.start("tenant-a", payload)
    assert first[0] == second[0]
    assert len(await repository.list("tenant-a")) == 1
    assert len(await repository.list("tenant-b")) == 0
    updated = await repository.update("tenant-a", "siprec-1", PbxCallStatus(status="completed", asr_degraded=True))
    assert updated[4] == "completed"
    assert updated[11] == 1
