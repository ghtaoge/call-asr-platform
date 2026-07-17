from app.asr.sensevoice_provider import SenseVoiceProvider
from app.core.models import Speaker


class FakeSenseVoice:
    def generate(self, **kwargs):
        return [
            {
                "text": "完整文本",
                "sentence_info": [
                    {"start": 600, "end": 1500, "text": "您好。"},
                    {"start": 1800, "end": 3200, "sentence": "请问需要什么？"},
                ],
            }
        ]


def test_sensevoice_returns_atomic_timestamped_segments():
    provider = SenseVoiceProvider(model=FakeSenseVoice())
    segments = provider._parse_result(
        FakeSenseVoice().generate(),
        "call_1",
        Speaker.sales,
        4000,
    )
    assert [(segment.start_ms, segment.end_ms, segment.text) for segment in segments] == [
        (600, 1500, "您好。"),
        (1800, 3200, "请问需要什么？"),
    ]
    assert all(segment.speaker == Speaker.sales for segment in segments)


def test_sensevoice_splits_punctuated_text_using_word_timestamps():
    provider = SenseVoiceProvider(model=FakeSenseVoice())
    result = [{
        "text": "<|zh|><|NEUTRAL|>您好。请问需要什么？",
        "timestamp": [
            [100, 220], [220, 380],
            [500, 620], [620, 740], [740, 860], [860, 980],
            [980, 1100], [1100, 1220],
        ],
    }]

    segments = provider._parse_result(result, "call_1", Speaker.customer, 1500)

    assert [(segment.start_ms, segment.end_ms, segment.text) for segment in segments] == [
        (100, 380, "您好。"),
        (500, 1220, "请问需要什么？"),
    ]
