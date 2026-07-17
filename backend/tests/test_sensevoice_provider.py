import sys
from types import SimpleNamespace

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


def test_default_loader_uses_vad_without_external_punctuation(monkeypatch):
    options = {}

    def fake_auto_model(**kwargs):
        options.update(kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=fake_auto_model))

    SenseVoiceProvider()._get_model()

    assert options["model"] == "paraformer-zh"
    assert options["vad_model"] == "fsmn-vad"
    assert options["vad_kwargs"]["max_single_segment_time"] == 15_000
    assert options["punc_model"] == "ct-punc"


def test_transcribe_uses_native_timestamps_and_merges_comma_fragments():
    class FakeParaformer:
        vad_model = None

        def __init__(self):
            self.options = None

        def generate(self, **kwargs):
            self.options = kwargs
            return [{
                "text": "喂，您好。请问，需要什么？",
                "sentence_info": [
                    {"start": 100, "end": 300, "text": "喂，"},
                    {"start": 320, "end": 900, "text": "您好。"},
                    {"start": 1500, "end": 1900, "text": "请问，"},
                    {"start": 1900, "end": 2800, "text": "需要什么？"},
                ],
            }]

    model = FakeParaformer()
    segments = SenseVoiceProvider(model=model).transcribe_file(
        "missing.wav", "call_1", Speaker.customer
    )

    assert model.options["sentence_timestamp"] is True
    assert [(item.start_ms, item.end_ms, item.text) for item in segments] == [
        (100, 900, "喂，您好。"),
        (1500, 2800, "请问，需要什么？"),
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
        "sentence_info": [],
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
