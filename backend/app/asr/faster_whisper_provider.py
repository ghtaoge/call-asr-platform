from app.core.models import Segment, Speaker
from app.postprocess.text import add_basic_punctuation


class FasterWhisperProvider:
    def __init__(self, model_size: str = "base", device: str = "cpu") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Install backend optional dependency group 'models' to use faster-whisper.") from exc
        compute_type = "float16" if device == "cuda" else "int8"
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: bytes, session_id: str, speaker: Speaker = Speaker.unknown) -> list[Segment]:
        raise RuntimeError("FasterWhisperProvider expects a file path integration in the session service.")

    def transcribe_file(self, path: str, session_id: str, speaker: Speaker = Speaker.unknown) -> list[Segment]:
        segments, _ = self._model.transcribe(path, vad_filter=True)
        results: list[Segment] = []
        for index, item in enumerate(segments, start=1):
            results.append(
                Segment(
                    id=f"{session_id}_seg_{index:03d}",
                    session_id=session_id,
                    speaker=speaker,
                    start_ms=int(item.start * 1000),
                    end_ms=int(item.end * 1000),
                    text=add_basic_punctuation(item.text.strip()),
                    confidence=0.9,
                    is_final=True,
                )
            )
        return results
