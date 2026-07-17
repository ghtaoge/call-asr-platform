import aiosqlite

from app.jobs.models import JobStage, JobStatus, ModuleStatus
from app.jobs.repository import JobRepository


async def test_job_repository_persists_progress_and_recovers_running_jobs(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    await repo.init()
    await repo.create("job_1", "call_1", "upload")
    await repo.update_progress("job_1", JobStage.transcribing_sales, 15)
    job = await repo.require("job_1")
    assert job.status == JobStatus.running
    assert job.progress == 15
    assert await repo.mark_running_interrupted() == 1
    assert (await repo.require("job_1")).status == JobStatus.interrupted


async def test_repository_migrates_completed_legacy_jobs_without_overwriting_new_states(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    async with aiosqlite.connect(database) as db:
        await db.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, source_type TEXT NOT NULL,
                source_url TEXT, source_path TEXT, source_content_type TEXT,
                status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL,
                summary_status TEXT NOT NULL, error_code TEXT, error_message TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            INSERT INTO jobs (
                id, session_id, source_type, status, stage, progress,
                summary_status, created_at, updated_at
            ) VALUES ('legacy', 'call_legacy', 'upload', 'completed', 'completed', 100,
                      'completed', '2026-07-17', '2026-07-17')
            """
        )
        await db.commit()

    repo = JobRepository(database)
    await repo.init()
    migrated = await repo.require("legacy")
    assert migrated.transcript_status == ModuleStatus.completed
    assert migrated.emotion_status == ModuleStatus.completed

    await repo.set_module_status(
        "legacy", "emotion", ModuleStatus.failed, "emotion_failed", "情绪分析失败"
    )
    await repo.init()
    assert (await repo.require("legacy")).emotion_status == ModuleStatus.failed
