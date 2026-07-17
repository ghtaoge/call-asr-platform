from app.asr.mock_provider import MockAsrProvider
from app.emotion.provider import RuleEmotionProvider
from app.translation.provider import LocalTranslationProvider


def test_mock_asr_returns_segment_from_bytes():
    provider = MockAsrProvider()

    segments = provider.transcribe(b"fake-audio", session_id="s1", speaker="sales")

    assert segments[0].session_id == "s1"
    assert segments[0].speaker == "sales"
    assert "您好" in segments[0].text
    assert segments[0].is_final is True


def test_emotion_detects_angry_text():
    provider = RuleEmotionProvider()

    result = provider.analyze("我很生气，你们必须处理")

    assert result.label == "angry"
    assert result.confidence >= 0.8
    assert result.score < 0


def test_translation_provider_marks_target_language():
    provider = LocalTranslationProvider()

    result = provider.translate("您好", source_language="zh", target_language="en")

    assert result == "[en] 您好"
