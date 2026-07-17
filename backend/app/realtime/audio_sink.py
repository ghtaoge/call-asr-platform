import wave
from pathlib import Path

from app.realtime.protocol import AudioFrame


class RealtimeAudioSink:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._writer = wave.open(str(path), "wb")
        self._writer.setnchannels(1)
        self._writer.setsampwidth(2)
        self._writer.setframerate(16_000)
        self._closed = False

    def append(self, frame: AudioFrame) -> None:
        if self._closed:
            raise RuntimeError("realtime audio sink is closed")
        self._writer.writeframesraw(frame.payload)

    def close(self) -> Path:
        if not self._closed:
            self._writer.close()
            self._closed = True
        return self.path
