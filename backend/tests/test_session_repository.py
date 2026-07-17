from app.core.models import EmotionResult, Segment, SegmentRiskArtifact, Speaker
from app.sessions.repository import SessionRepository


async def test_repository_merges_analysis_artifacts_without_overwriting_transcript(tmp_path):
    repository = SessionRepository(tmp_path / "sessions.sqlite3")
    await repository.init()
    segment = Segment(
        id="segment_1",
        session_id="call_1",
        speaker=Speaker.sales,
        start_ms=0,
        end_ms=1000,
        text="您好。",
    )
    await repository.save_segments("call_1", [segment])
    await repository.save_emotions(
        "call_1",
        {"segment_1": EmotionResult(label="angry", confidence=0.8, score=-0.8)},
    )
    await repository.save_risks(
        "call_1",
        {"segment_1": SegmentRiskArtifact()},
    )

    enriched = await repository.list_enriched_segments("call_1")
    assert enriched[0].text == "您好。"
    assert enriched[0].emotion.label == "angry"
