from app.audio.preprocessor import AudioProcessingResult, ChannelSplitResult
from app.core.models import EmotionResult, QualityScore, Segment, Speaker
from app.sessions.pipeline import AnalysisPipeline, merge_channel_segments


def segment(identifier, speaker, start, end, text):
    return Segment(
        id=identifier,
        session_id="call_1",
        speaker=speaker,
        start_ms=start,
        end_ms=end,
        text=text,
    )


def test_merge_channel_segments_interleaves_by_real_time():
    sales = [
        segment("s1", Speaker.sales, 0, 1000, "您好。"),
        segment("s2", Speaker.sales, 4000, 5000, "可以。"),
    ]
    customer = [segment("c1", Speaker.customer, 1200, 2500, "我要退款。")]
    assert [item.id for item in merge_channel_segments(sales, customer)] == ["s1", "c1", "s2"]


def test_pipeline_maps_second_channel_to_sales_and_first_to_customer():
    class Audio:
        def split_required_stereo(self, audio):
            return ChannelSplitResult(left=b"channel-1", right=b"channel-2", is_stereo=True, original=audio)

        def process(self, audio):
            return AudioProcessingResult(audio=audio, silence_ratio=0.1, noise_level="low")

    class Asr:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, session_id, speaker):
            self.calls.append((audio, speaker))
            return [segment(f"{speaker.value}-1", speaker, 0, 1000, "您好。")]

    class Emotion:
        def __init__(self):
            self.calls = []

        def analyze_many(self, requests):
            self.calls.append(requests)
            return [EmotionResult(label="neutral", confidence=0.8, score=0) for _ in requests]

    class Sensitive:
        def scan(self, *args):
            return []

    class Compliance:
        def check(self, segment):
            return []

    class Quality:
        def score(self, *args):
            return QualityScore(
                score=90, noise_level="low", silence_ratio=0.1,
                sales_talk_ratio=0.5, customer_talk_ratio=0.5,
                interruptions=0, negative_emotion_ratio=0, risk_hit_count=0,
            )

    asr = Asr()
    emotion = Emotion()
    pipeline = AnalysisPipeline(Audio(), asr, emotion, Sensitive(), Compliance(), Quality())
    pipeline.run(b"audio", "call_1", lambda stage, progress: None)

    assert asr.calls == [(b"channel-2", Speaker.sales), (b"channel-1", Speaker.customer)]
    assert emotion.calls == [[
        (b"channel-1", 0, 1000),
        (b"channel-2", 0, 1000),
    ]]


def test_pipeline_uses_one_remote_batch_request_for_both_channels():
    class Audio:
        def split_required_stereo(self, audio):
            return ChannelSplitResult(left=b"customer", right=b"sales", is_stereo=True, original=audio)

    class Rpc:
        def __init__(self):
            self.calls = []

        def batch_recognize(self, tenant_id, job_id, channels):
            self.calls.append((tenant_id, job_id, channels))
            return [
                type("Remote", (), {"speaker": "sales", "start_ms": 0, "end_ms": 800, "text": "销售您好。", "confidence": 0.9})(),
                type("Remote", (), {"speaker": "customer", "start_ms": 900, "end_ms": 1500, "text": "客户您好。", "confidence": 0.8})(),
            ]

    pipeline = AnalysisPipeline(
        Audio(), object(), object(), object(), object(), object(), batch_rpc=Rpc()
    )
    pipeline.batch_rpc.calls = []
    result = pipeline.transcribe(b"audio", "call_1", lambda stage, progress: None)
    assert [item.speaker for item in result.segments] == [Speaker.sales, Speaker.customer]
    assert pipeline.batch_rpc.calls == [("default", "call_1", [("sales", b"sales"), ("customer", b"customer")])]
