from fastapi.testclient import TestClient

from app.core.models import CallSummary, EmotionResult, QualityScore, Segment, Speaker
from app.jobs.models import JobAnalysisResponse, JobCreateResponse, JobStage, JobStatus, SummaryStatus
from app.main import create_app


class CompletedManager:
    async def create_upload(self, audio, content_type):
        assert audio == b"audio"
        return JobCreateResponse(
            job_id="job_1",
            session_id="call_1",
            status=JobStatus.queued,
            stage=JobStage.queued,
            progress=0,
        )

    async def wait(self, job_id):
        return None

    async def get_result(self, job_id):
        return JobAnalysisResponse(
            job_id=job_id,
            session_id="call_1",
            summary_status=SummaryStatus.completed,
            segments=[Segment(
                id="s1", session_id="call_1", speaker=Speaker.sales,
                start_ms=0, end_ms=1000, text="您好。",
                emotion=EmotionResult(label="neutral", confidence=0.9, score=0),
            )],
            quality=QualityScore(
                score=90, noise_level="low", silence_ratio=0,
                sales_talk_ratio=1, customer_talk_ratio=0, interruptions=0,
                negative_emotion_ratio=0, risk_hit_count=0,
            ),
            summary=CallSummary(overview="销售向客户问候。"),
        )


def test_offline_upload_returns_segments_and_summary():
    app = create_app()
    app.state.job_manager = CompletedManager()
    client = TestClient(app)
    response = client.post(
        "/api/sessions/offline",
        files={"file": ("call.wav", b"audio", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.headers["deprecation"] == "true"
    body = response.json()
    assert body["session_id"] == "call_1"
    assert body["segments"][0]["text"] == "您好。"
    assert body["summary"]["overview"] == "销售向客户问候。"
