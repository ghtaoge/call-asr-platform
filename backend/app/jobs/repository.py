from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from app.jobs.models import JobRecord, JobStage, JobStatus, SummaryStatus


CREATE_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_path TEXT,
    source_content_type TEXT,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL,
    summary_status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class JobRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(CREATE_JOBS_SQL)
            await db.commit()

    async def create(
        self,
        job_id: str,
        session_id: str,
        source_type: str,
        source_url: str | None = None,
    ) -> JobRecord:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                INSERT INTO jobs (
                    id, session_id, source_type, source_url, status, stage,
                    progress, summary_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, session_id, source_type, source_url,
                    JobStatus.queued.value, JobStage.queued.value, 0,
                    SummaryStatus.pending.value, now, now,
                ),
            )
            await db.commit()
        return await self.require(job_id)

    async def get(self, job_id: str) -> JobRecord | None:
        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["job_id"] = payload.pop("id")
        return JobRecord.model_validate(payload)

    async def require(self, job_id: str) -> JobRecord:
        job = await self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    async def set_source(self, job_id: str, path: Path, content_type: str) -> None:
        await self._update(job_id, source_path=str(path), source_content_type=content_type)

    async def update_progress(self, job_id: str, stage: JobStage, progress: int) -> None:
        await self._update(
            job_id,
            status=JobStatus.running.value,
            stage=stage.value,
            progress=max(0, min(progress, 100)),
            error_code=None,
            error_message=None,
        )

    async def complete(self, job_id: str) -> None:
        await self._update(
            job_id,
            status=JobStatus.completed.value,
            stage=JobStage.completed.value,
            progress=100,
        )

    async def fail(self, job_id: str, code: str, message: str) -> None:
        await self._update(
            job_id,
            status=JobStatus.failed.value,
            stage=JobStage.failed.value,
            error_code=code,
            error_message=message,
        )

    async def set_summary_status(
        self,
        job_id: str,
        status: SummaryStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await self._update(
            job_id,
            summary_status=status.value,
            error_code=error_code,
            error_message=error_message,
        )

    async def mark_running_interrupted(self) -> int:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """
                UPDATE jobs
                SET status = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE status = ?
                """,
                (
                    JobStatus.interrupted.value,
                    "interrupted",
                    "服务重启，任务已中断，请重新提交",
                    now,
                    JobStatus.running.value,
                ),
            )
            await db.commit()
            return cursor.rowcount

    async def delete(self, job_id: str) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            await db.commit()

    async def _update(self, job_id: str, **values: object) -> None:
        if not values:
            return
        values["updated_at"] = datetime.now(UTC).isoformat()
        columns = ", ".join(f"{name} = ?" for name in values)
        params = [*values.values(), job_id]
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                f"UPDATE jobs SET {columns} WHERE id = ?",  # Names are internal constants.
                params,
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            await db.commit()
