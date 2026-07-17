from pathlib import Path

from fastapi.testclient import TestClient

from app.jobs.manager import JobNotReadyError
from app.jobs.models import JobCreateResponse, JobStage, JobStatus, JobStatusResponse, SummaryStatus
from app.main import create_app


class FakeManager:
    def __init__(self, audio_path: Path | None = None):
        self.audio_path = audio_path

    async def create_upload(self, audio, content_type):
        return self.created()

    async def create_url(self, audio_url):
        return self.created()

    async def get_status(self, job_id):
        completed = self.audio_path is not None
        payload = self.created().model_dump()
        payload.update(
            status=JobStatus.completed if completed else JobStatus.running,
            stage=JobStage.completed if completed else JobStage.transcribing_sales,
            progress=100 if completed else 15,
            summary_status=SummaryStatus.pending,
        )
        return JobStatusResponse(**payload)

    async def get_result(self, job_id):
        raise JobNotReadyError(job_id)

    async def retry_summary(self, job_id):
        return await self.get_status(job_id)

    async def get_audio(self, job_id):
        if self.audio_path is None:
            raise JobNotReadyError(job_id)
        return self.audio_path, "audio/wav"

    @staticmethod
    def created():
        return JobCreateResponse(
            job_id="job_1",
            session_id="call_1",
            status=JobStatus.queued,
            stage=JobStage.queued,
            progress=0,
        )


def client_with(manager):
    app = create_app()
    client = TestClient(app)
    client.app.state.job_manager = manager
    return client


def test_upload_and_url_create_accepted_jobs():
    client = client_with(FakeManager())
    upload = client.post(
        "/api/jobs/upload",
        files={"file": ("call.wav", b"audio", "audio/wav")},
    )
    url = client.post("/api/jobs/url", json={"audio_url": "https://example.com/call.wav"})
    assert upload.status_code == 202
    assert url.status_code == 202


def test_status_is_lightweight_and_result_waits_for_completion():
    client = client_with(FakeManager())
    status = client.get("/api/jobs/job_1")
    result = client.get("/api/jobs/job_1/result")
    assert "segments" not in status.json()
    assert result.status_code == 409


def test_audio_endpoint_supports_ranges(tmp_path):
    path = tmp_path / "source.wav"
    path.write_bytes(b"0123456789")
    client = client_with(FakeManager(path))
    response = client.get("/api/jobs/job_1/audio", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"0123"
    assert response.headers["content-range"] == "bytes 0-3/10"
