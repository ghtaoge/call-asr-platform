from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.tts.manager import TtsValidationError
from app.tts.models import TtsJobResponse, TtsJobStatus, TtsVoiceResponse


class FakeTtsManager:
    def __init__(self, audio_path: Path):
        self.audio_path = audio_path

    async def create_voice(self, audio, filename, consent):
        if not consent:
            raise TtsValidationError("请先确认已获得声音使用授权")
        return TtsVoiceResponse(
            voice_id="voice_1",
            prompt_text="参考声音。",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )

    def list_preset_voices(self):
        from app.tts.models import TtsPresetVoiceResponse

        return [TtsPresetVoiceResponse(
            id="zh_female",
            voice_id="preset:zh_female",
            label="普通话女声",
            language="普通话",
            gender="female",
        )]

    async def health(self):
        from app.tts.models import TtsHealthResponse, TtsHealthStatus

        return TtsHealthResponse(
            status=TtsHealthStatus.ready,
            model="CosyVoice",
            message="语音合成服务可用",
            checked_at=datetime.now(UTC),
        )

    async def create_job(self, voice_id, text):
        return TtsJobResponse(job_id="tts_1", voice_id=voice_id, status=TtsJobStatus.queued)

    async def get_job(self, job_id):
        return TtsJobResponse(job_id=job_id, voice_id="voice_1", status=TtsJobStatus.completed)

    async def get_audio(self, job_id):
        return self.audio_path


def client_with(manager):
    app = create_app()
    app.state.tts_manager = manager
    return TestClient(app)


def test_voice_consent_and_generated_audio_headers(tmp_path):
    audio = tmp_path / "result.wav"
    audio.write_bytes(b"0123456789")
    client = client_with(FakeTtsManager(audio))
    denied = client.post(
        "/api/tts/voices/clone",
        files={"file": ("voice.wav", b"audio", "audio/wav")},
        data={"consent": "false"},
    )
    assert denied.status_code == 400
    assert "授权" in denied.json()["detail"]

    response = client.get("/api/tts/jobs/tts_1/audio", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"0123"
    assert response.headers["x-audio-origin"] == "ai-generated"

    download = client.get("/api/tts/jobs/tts_1/audio?download=true")
    assert "ai-generated-tts_1.wav" in download.headers["content-disposition"]


def test_lists_default_voices_and_accepts_preset_job(tmp_path):
    client = client_with(FakeTtsManager(tmp_path / "result.wav"))
    presets = client.get("/api/tts/voices/presets")
    assert presets.status_code == 200
    assert presets.json()[0] == {
        "id": "zh_female",
        "voice_id": "preset:zh_female",
        "label": "普通话女声",
        "language": "普通话",
        "gender": "female",
    }

    created = client.post(
        "/api/tts/jobs",
        json={"voice_id": "preset:zh_female", "text": "默认音色。"},
    )
    assert created.status_code == 202
    assert created.json()["voice_id"] == "preset:zh_female"


def test_tts_health_is_available_before_submission(tmp_path):
    client = client_with(FakeTtsManager(tmp_path / "result.wav"))
    response = client.get("/api/tts/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
