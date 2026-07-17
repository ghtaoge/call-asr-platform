import re
import shutil
from pathlib import Path


ID_PATTERN = re.compile(r"^[a-z0-9_]+$")
ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac"}


class TtsStorageLimitError(ValueError):
    pass


class TtsStorage:
    def __init__(self, root: Path, max_reference_bytes: int) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_reference_bytes = max_reference_bytes

    def save_reference(self, voice_id: str, audio: bytes, suffix: str) -> Path:
        if len(audio) > self.max_reference_bytes:
            raise TtsStorageLimitError("参考音频不能超过 20 MB")
        suffix = suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise TtsStorageLimitError("参考音频仅支持 WAV、MP3、M4A 或 AAC")
        directory = self._directory("voices", voice_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"source{suffix}"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(audio)
        temporary.replace(path)
        return path

    def prompt_path(self, voice_id: str) -> Path:
        return self._directory("voices", voice_id) / "prompt.wav"

    def output_path(self, job_id: str) -> Path:
        directory = self._directory("jobs", job_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "result.wav"

    def delete_voice(self, voice_id: str) -> None:
        shutil.rmtree(self._directory("voices", voice_id), ignore_errors=True)

    def delete_job(self, job_id: str) -> None:
        shutil.rmtree(self._directory("jobs", job_id), ignore_errors=True)

    def _directory(self, category: str, identifier: str) -> Path:
        if not ID_PATTERN.fullmatch(identifier):
            raise ValueError("invalid TTS identifier")
        path = (self.root / category / identifier).resolve()
        if self.root not in path.parents:
            raise ValueError("TTS path escapes storage root")
        return path
