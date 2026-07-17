from datetime import UTC, datetime, timedelta

import pytest
import aiosqlite

from app.tts.models import TtsJobStatus
from app.tts.repository import TtsRepository, VoiceExpiredError


async def test_voice_and_job_lifecycle(tmp_path):
    repository = TtsRepository(tmp_path / "tts.sqlite3")
    await repository.init()
    voice = await repository.create_voice(
        "voice_1",
        tmp_path / "prompt.wav",
        "您好，这是参考声音。",
        datetime.now(UTC) + timedelta(days=7),
    )
    job = await repository.create_job("tts_1", voice.id, "需要合成的文字。")
    assert job.status == TtsJobStatus.queued
    await repository.set_job_status("tts_1", TtsJobStatus.completed, tmp_path / "result.wav")
    assert (await repository.require_job("tts_1")).status == TtsJobStatus.completed


async def test_expired_voice_cannot_create_job(tmp_path):
    repository = TtsRepository(tmp_path / "tts.sqlite3")
    await repository.init()
    now = datetime.now(UTC)
    async with aiosqlite.connect(tmp_path / "tts.sqlite3") as db:
        await db.execute(
            "INSERT INTO tts_voices VALUES (?, ?, ?, ?, ?)",
            (
                "voice_old",
                str(tmp_path / "prompt.wav"),
                "参考声音。",
                (now - timedelta(seconds=1)).isoformat(),
                now.isoformat(),
            ),
        )
        await db.commit()
    with pytest.raises(VoiceExpiredError):
        await repository.create_job("tts_2", "voice_old", "文本")


async def test_restart_and_retention_cleanup_recover_stale_jobs(tmp_path):
    database = tmp_path / "tts.sqlite3"
    repository = TtsRepository(database)
    await repository.init()
    now = datetime.now(UTC)
    await repository.create_voice(
        "voice_1", tmp_path / "prompt.wav", "参考声音。", now + timedelta(days=7)
    )
    await repository.create_job("tts_running", "voice_1", "合成内容")
    await repository.set_job_status("tts_running", TtsJobStatus.running)

    await repository.mark_running_failed()
    interrupted = await repository.require_job("tts_running")
    assert interrupted.status == TtsJobStatus.failed
    assert interrupted.error_code == "interrupted"

    async with aiosqlite.connect(database) as db:
        await db.execute(
            "UPDATE tts_jobs SET created_at = ? WHERE id = ?",
            ((now - timedelta(days=8)).isoformat(), "tts_running"),
        )
        await db.commit()
    voice_ids, job_ids = await repository.delete_expired(now, now - timedelta(days=7))
    assert voice_ids == []
    assert job_ids == ["tts_running"]
    with pytest.raises(KeyError):
        await repository.require_job("tts_running")
