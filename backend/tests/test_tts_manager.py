import asyncio
import io
import wave

from app.core.inference_gate import InferenceGate
from app.core.models import Segment, Speaker
from app.tts.manager import TtsManager
from app.tts.models import TtsJobStatus
from app.tts.repository import TtsRepository
from app.tts.storage import TtsStorage


def wav(seconds=5):
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x01\x00" * int(16000 * seconds))
    return output.getvalue()


class Audio:
    def normalize_mono_wav(self, audio):
        return audio


class Asr:
    def transcribe(self, audio, session_id, speaker):
        return [Segment(
            id="prompt", session_id=session_id, speaker=Speaker.unknown,
            start_ms=0, end_ms=1000, text="您好，这是参考声音。",
        )]


class Provider:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text, prompt_text, prompt_path, output_path):
        self.calls.append(text)
        output_path.write_bytes(wav(1))

    async def close(self):
        pass


async def test_voice_creation_and_tts_queue(tmp_path):
    repository = TtsRepository(tmp_path / "database.sqlite3")
    provider = Provider()
    manager = TtsManager(
        repository,
        TtsStorage(tmp_path / "tts", 20 * 1024 * 1024),
        Audio(),
        Asr(),
        provider,
        InferenceGate(),
        7,
    )
    await manager.start()
    voice = await manager.create_voice(wav(), "voice.wav", True)
    job = await manager.create_job(voice.voice_id, "需要合成的文字。")
    await manager.wait(job.job_id)
    completed = await repository.require_job(job.job_id)
    assert completed.status == TtsJobStatus.completed
    assert provider.calls == ["需要合成的文字。"]
    await manager.close()


async def test_tts_waits_while_realtime_is_active(tmp_path):
    gate = InferenceGate()
    await gate.realtime_started()
    repository = TtsRepository(tmp_path / "database.sqlite3")
    provider = Provider()
    manager = TtsManager(
        repository, TtsStorage(tmp_path / "tts", 1024 * 1024),
        Audio(), Asr(), provider, gate, 7,
    )
    await manager.start()
    # Register directly because reference ASR correctly waits behind the same realtime gate.
    prompt = manager.storage.prompt_path("voice_1")
    prompt.parent.mkdir(parents=True)
    prompt.write_bytes(wav())
    from datetime import UTC, datetime, timedelta
    await repository.create_voice("voice_1", prompt, "参考声音。", datetime.now(UTC) + timedelta(days=7))
    job = await manager.create_job("voice_1", "排队文本")
    await asyncio.sleep(0.05)
    assert provider.calls == []
    await gate.realtime_ended()
    await manager.wait(job.job_id)
    assert provider.calls == ["排队文本"]
    await manager.close()
