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


def test_sensevoice_builds_clean_sentences_from_vad_intervals():
    provider = SenseVoiceProvider(model=FakeSenseVoice())
    raw_text = (
        "< | zh | > < | HAPPY | > < | S pe ech | > < | withi tn | >喂，，您好。。"
        "<|zh|><|NEUTRAL|><|Speech|><|withitn|>请问需要什么？？"
    )

    segments = provider._segments_from_vad_text(
        raw_text,
        [[100, 1100], [2000, 3600]],
        "call_1",
        Speaker.customer,
    )

    assert [(segment.start_ms, segment.end_ms, segment.text) for segment in segments] == [
        (100, 1100, "喂，您好。"),
        (2000, 3600, "请问需要什么？"),
    ]
    assert all("<" not in segment.text and "|" not in segment.text for segment in segments)


def test_sensevoice_splits_long_utterances_at_natural_commas():
    text = "客户昨天已经提交申请，我们今天需要核实物流状态，然后联系快递员确认情况，最后把处理结果及时回复客户。"

    sentences = SenseVoiceProvider._split_sentences(text)

    assert len(sentences) >= 2
    assert "".join(sentences) == text
    assert all(len(sentence) <= 36 for sentence in sentences)
