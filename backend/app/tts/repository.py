from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from app.tts.models import TtsJob, TtsJobStatus, TtsVoice


class VoiceExpiredError(RuntimeError):
    pass


class TtsRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tts_voices (
                    id TEXT PRIMARY KEY, prompt_path TEXT NOT NULL, prompt_text TEXT NOT NULL,
                    expires_at TEXT NOT NULL, created_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tts_jobs (
                    id TEXT PRIMARY KEY, voice_id TEXT NOT NULL, text TEXT NOT NULL,
                    status TEXT NOT NULL, output_path TEXT, error_code TEXT, error_message TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def create_voice(
        self,
        voice_id: str,
        prompt_path: Path,
        prompt_text: str,
        expires_at: datetime,
    ) -> TtsVoice:
        now = datetime.now(UTC)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                "INSERT INTO tts_voices VALUES (?, ?, ?, ?, ?)",
                (voice_id, str(prompt_path), prompt_text, expires_at.isoformat(), now.isoformat()),
            )
            await db.commit()
        return await self.require_voice(voice_id)

    async def require_voice(self, voice_id: str) -> TtsVoice:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM tts_voices WHERE id = ?", (voice_id,)
            )).fetchone()
        if row is None:
            raise KeyError(voice_id)
        voice = TtsVoice.model_validate(dict(row))
        if voice.expires_at <= datetime.now(UTC):
            raise VoiceExpiredError(voice_id)
        return voice

    async def create_job(
        self,
        job_id: str,
        voice_id: str,
        text: str,
        *,
        validate_voice: bool = True,
    ) -> TtsJob:
        if validate_voice:
            await self.require_voice(voice_id)
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                "INSERT INTO tts_jobs VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?)",
                (job_id, voice_id, text, TtsJobStatus.queued.value, now, now),
            )
            await db.commit()
        return await self.require_job(job_id)

    async def require_job(self, job_id: str) -> TtsJob:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM tts_jobs WHERE id = ?", (job_id,)
            )).fetchone()
        if row is None:
            raise KeyError(job_id)
        return TtsJob.model_validate(dict(row))

    async def set_job_status(
        self,
        job_id: str,
        status: TtsJobStatus,
        output_path: Path | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                UPDATE tts_jobs SET status = ?, output_path = ?, error_code = ?,
                    error_message = ?, updated_at = ? WHERE id = ?
                """,
                (
                    status.value,
                    str(output_path) if output_path else None,
                    error_code,
                    error_message,
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            await db.commit()

    async def mark_running_failed(self) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                UPDATE tts_jobs SET status = 'failed', error_code = 'interrupted',
                    error_message = '服务重启，语音合成任务已中断', updated_at = ?
                WHERE status = 'running'
                """,
                (datetime.now(UTC).isoformat(),),
            )
            await db.commit()

    async def delete_expired(
        self,
        now: datetime,
        job_cutoff: datetime,
    ) -> tuple[list[str], list[str]]:
        async with aiosqlite.connect(self.database_path) as db:
            voice_rows = await (await db.execute(
                "SELECT id FROM tts_voices WHERE expires_at <= ?",
                (now.isoformat(),),
            )).fetchall()
            job_rows = await (await db.execute(
                """
                SELECT id FROM tts_jobs
                WHERE created_at <= ? OR voice_id IN (
                    SELECT id FROM tts_voices WHERE expires_at <= ?
                )
                """,
                (job_cutoff.isoformat(), now.isoformat()),
            )).fetchall()
            voice_ids = [row[0] for row in voice_rows]
            job_ids = [row[0] for row in job_rows]
            if job_ids:
                placeholders = ",".join("?" for _ in job_ids)
                await db.execute(f"DELETE FROM tts_jobs WHERE id IN ({placeholders})", job_ids)
            if voice_ids:
                placeholders = ",".join("?" for _ in voice_ids)
                await db.execute(f"DELETE FROM tts_voices WHERE id IN ({placeholders})", voice_ids)
            await db.commit()
        return voice_ids, job_ids
