from app.core.models import Segment, Speaker
from app.sessions.pipeline import merge_channel_segments


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
