import asyncio

from app.core.models import CallSummary, EmotionResult, QualityScore, Segment, Speaker
from app.jobs.manager import JobManager
from app.jobs.models import JobStage, JobStatus, SummaryStatus
from app.jobs.repository import JobRepository
from app.jobs.storage import JobStorage
from app.sessions.pipeline import LocalAnalysisResult
from app.sessions.repository import SessionRepository
from app.summary.deepseek import SummaryError


class FakePipeline:
    def run(self, audio, session_id, progress):
        progress(JobStage.transcribing_sales, 15)
        segment = Segment(
            id=f"{session_id}_s1",
            session_id=session_id,
            speaker=Speaker.sales,
            start_ms=0,
            end_ms=1000,
            text="您好。",
            emotion=EmotionResult(label="neutral", confidence=0.9, score=0),
        )
        quality = QualityScore(
            score=90,
            noise_level="low",
            silence_ratio=0.1,
            sales_talk_ratio=1,
            customer_talk_ratio=0,
            interruptions=0,
            negative_emotion_ratio=0,
            risk_hit_count=0,
            suggestions=[],
        )
        return LocalAnalysisResult([segment], quality)


class FakeSummary:
    async def generate(self, segments):
        return CallSummary(overview="销售已问候客户")


class FailingSummary:
    async def generate(self, segments):
        raise SummaryError("summary_timeout", "摘要生成超时")


class BlockingSummary:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, segments):
        self.started.set()
        await self.release.wait()
        return CallSummary(overview="摘要稍后完成")


class UnusedDownloader:
    def download(self, url, destination):
        raise AssertionError("not used")


async def build_manager(tmp_path, summary):
    jobs = JobRepository(tmp_path / "database.sqlite3")
    sessions = SessionRepository(tmp_path / "database.sqlite3")
    await jobs.init()
    await sessions.init()
    manager = JobManager(
        jobs=jobs,
        sessions=sessions,
        storage=JobStorage(tmp_path / "jobs", 7, 1024),
        pipeline=FakePipeline(),
        summary=summary,
        downloader=UnusedDownloader(),
    )
    return manager, jobs


async def test_manager_persists_completed_result(tmp_path):
    manager, jobs = await build_manager(tmp_path, FakeSummary())
    job = await manager.create_upload(b"audio", "audio/wav")
    await manager.wait(job.job_id)
    status = await jobs.require(job.job_id)
    assert status.status == JobStatus.completed
    assert status.summary_status == SummaryStatus.completed
    assert (await manager.get_result(job.job_id)).summary.overview == "销售已问候客户"
    await manager.close()


async def test_summary_failure_does_not_fail_local_analysis(tmp_path):
    manager, jobs = await build_manager(tmp_path, FailingSummary())
    job = await manager.create_upload(b"audio", "audio/wav")
    await manager.wait(job.job_id)
    status = await jobs.require(job.job_id)
    assert status.status == JobStatus.completed
    assert status.summary_status == SummaryStatus.failed
    assert (await manager.get_result(job.job_id)).segments
    await manager.close()


async def test_local_result_is_available_while_summary_is_still_running(tmp_path):
    summary = BlockingSummary()
    manager, jobs = await build_manager(tmp_path, summary)
    job = await manager.create_upload(b"audio", "audio/wav")

    await asyncio.wait_for(summary.started.wait(), timeout=2)
    status = await jobs.require(job.job_id)
    assert status.status == JobStatus.completed
    assert status.summary_status == SummaryStatus.running
    assert (await manager.get_result(job.job_id)).segments

    summary.release.set()
    await manager.wait(job.job_id)
    assert (await jobs.require(job.job_id)).summary_status == SummaryStatus.completed
    await manager.close()
