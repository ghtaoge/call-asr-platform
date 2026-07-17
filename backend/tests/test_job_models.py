from app.core.config import Settings
from app.core.models import CallSummary, EmotionResult
from app.jobs.models import JobStage, JobStatus, JobStatusResponse, SummaryStatus


def test_analysis_contracts_have_job_and_emotion_fields(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert settings.jobs_dir == tmp_path / "jobs"
    assert settings.deepseek_model == "deepseek-v4-pro"
    emotion = EmotionResult(label="angry", confidence=0.8, score=-0.8)
    assert emotion.score == -0.8
    summary = CallSummary(overview="客户要求退款")
    assert summary.overview == "客户要求退款"
    status = JobStatusResponse(
        job_id="job_1",
        session_id="call_1",
        status=JobStatus.running,
        stage=JobStage.transcribing_sales,
        progress=15,
        summary_status=SummaryStatus.pending,
    )
    assert status.progress == 15
