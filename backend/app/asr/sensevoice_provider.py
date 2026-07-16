import tempfile
import os

from app.core.models import Segment, Speaker
from app.postprocess.text import add_basic_punctuation


class SenseVoiceProvider:
    """ASR provider using Alibaba SenseVoice model via funasr."""

    def __init__(self) -> None:
        from funasr import AutoModel
        self._model = AutoModel(
            model="iic/SenseVoiceSmall",
            trust_remote_code=True,
        )

    def transcribe(self, audio: bytes, session_id: str, speaker: Speaker = Speaker.unknown) -> list[Segment]:
        # SenseVoice requires a file path, so write bytes to a temp WAV file
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(audio)
        tmp.close()

        try:
            res = self._model.generate(input=tmp.name, language="auto")
        finally:
            os.unlink(tmp.name)

        results: list[Segment] = []
        if res and len(res) > 0:
            # SenseVoice returns a list of results, each with text
            text_content = res[0].get("text", "") if isinstance(res[0], dict) else str(res[0])
            # Clean up SenseVoice special markers (emotion, language tags)
            text_content = self._clean_text(text_content)
            if text_content:
                results.append(
                    Segment(
                        id=f"{session_id}_seg_001",
                        session_id=session_id,
                        speaker=Speaker(speaker),
                        start_ms=0,
                        end_ms=max(1000, len(audio) * 10),
                        text=add_basic_punctuation(text_content),
                        confidence=0.92,
                        is_final=True,
                    )
                )

        # Fallback: if no text was produced, return empty list
        return results

    def _clean_text(self, text: str) -> str:
        """Remove SenseVoice special markers like <|zh|>, <|NEUTRAL|>, <|Speech|>."""
        import re
        # Remove language tags: <|zh|>, <|en|>, etc.
        text = re.sub(r"<\|[^|]+\|>", "", text)
        # Remove emotion/event tags: <|NEUTRAL|>, <|Speech|>, <|Music|>, etc.
        text = re.sub(r"<\|[A-Z_]+\|>", "", text)
        return text.strip()
