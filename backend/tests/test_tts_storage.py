import pytest

from app.tts.storage import TtsStorage, TtsStorageLimitError


def test_storage_uses_scoped_paths_and_enforces_limit(tmp_path):
    storage = TtsStorage(tmp_path / "tts", max_reference_bytes=20)
    prompt = storage.save_reference("voice_opaque", b"RIFF", ".wav")
    assert prompt == (tmp_path / "tts" / "voices" / "voice_opaque" / "source.wav").resolve()
    assert storage.output_path("tts_opaque").name == "result.wav"
    with pytest.raises(TtsStorageLimitError):
        storage.save_reference("voice_large", b"x" * 21, ".wav")
