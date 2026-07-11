from typing import Protocol

from app.core.models import Segment, Speaker


class AsrProvider(Protocol):
    def transcribe(self, audio: bytes, session_id: str, speaker: Speaker = Speaker.unknown) -> list[Segment]:
        ...
