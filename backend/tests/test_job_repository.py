from app.jobs.models import JobStage, JobStatus
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
