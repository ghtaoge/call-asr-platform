from app.core.models import Segment, Speaker
from app.postprocess.text import add_basic_punctuation


class MockAsrProvider:
    def transcribe(self, audio: bytes, session_id: str, speaker: Speaker = Speaker.unknown) -> list[Segment]:
        text = add_basic_punctuation("您好我是顾问 我想了解您的需求 可以说一下吗")
        return [
            Segment(
                id=f"{session_id}_seg_001",
                session_id=session_id,
                speaker=Speaker(speaker),
                start_ms=0,
                end_ms=max(1000, len(audio) * 10),
                text=text,
                confidence=0.92,
                is_final=True,
            )
        ]
