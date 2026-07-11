import pytest

from app.core.models import Segment, Speaker
from app.sessions.repository import SessionRepository


@pytest.mark.asyncio
async def test_repository_saves_and_loads_segments(tmp_path):
    repository = SessionRepository(tmp_path / "test.sqlite3")
    await repository.init()
    await repository.create_session("s1", mode="offline")
    segment = Segment(
        id="seg_1",
        session_id="s1",
        speaker=Speaker.sales,
        start_ms=0,
        end_ms=1000,
        text="您好。",
        confidence=0.9,
    )

    await repository.save_segments("s1", [segment])
    loaded = await repository.list_segments("s1")

    assert loaded == [segment]
