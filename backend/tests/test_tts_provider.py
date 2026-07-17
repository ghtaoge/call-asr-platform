from pathlib import Path

import httpx
import pytest

from app.tts.provider import CosyVoiceWorkerProvider, TtsProviderError


class FailingClient:
    async def post(self, *args, **kwargs):
        request = httpx.Request("POST", "http://127.0.0.1:18081/synthesize")
        raise httpx.ConnectError("worker unavailable", request=request)

    async def aclose(self):
        pass


class RecordingClient:
    def __init__(self):
        self.json = None

    async def post(self, *args, **kwargs):
        self.json = kwargs["json"]
        Path(self.json["output_path"]).write_bytes(b"RIFF" + b"x" * 2048)
        return httpx.Response(200, request=httpx.Request("POST", args[0]))

    async def aclose(self):
        pass


async def test_provider_bypasses_system_proxy_and_maps_connection_error(monkeypatch, tmp_path):
    options = {}

    def client_factory(**kwargs):
        options.update(kwargs)
        return FailingClient()

    monkeypatch.setattr("app.tts.provider.httpx.AsyncClient", client_factory)
    provider = CosyVoiceWorkerProvider("http://127.0.0.1:18081", "worker-token")

    assert options["trust_env"] is False
    with pytest.raises(TtsProviderError) as raised:
        await provider.synthesize(
            "需要合成的内容。",
            "参考文本。",
            tmp_path / "prompt.wav",
            tmp_path / "result.wav",
        )
    assert raised.value.code == "worker_unavailable"
    assert raised.value.public_message == "CosyVoice 工作进程不可用"
    await provider.close()


async def test_provider_sends_controlled_preset_speaker(monkeypatch, tmp_path):
    client = RecordingClient()
    monkeypatch.setattr("app.tts.provider.httpx.AsyncClient", lambda **kwargs: client)
    provider = CosyVoiceWorkerProvider("http://127.0.0.1:18081", "worker-token")

    await provider.synthesize_preset("欢迎使用。", "中文女", tmp_path / "result.wav")

    assert client.json["preset_speaker"] == "中文女"
    assert "prompt_path" not in client.json
    await provider.close()


async def test_provider_falls_back_to_windows_speech_for_builtin_voice(monkeypatch, tmp_path):
    provider = CosyVoiceWorkerProvider("http://127.0.0.1:18081", "worker-token")

    async def unavailable(*args, **kwargs):
        from app.tts.provider import TtsProviderError

        raise TtsProviderError("worker_unavailable", "CosyVoice 工作进程不可用")

    monkeypatch.setattr(provider, "_synthesize_preset_remote", unavailable)

    def fake_sapi(text, speaker, output_path):
        output_path.write_bytes(b"RIFF" + b"x" * 2048)

    monkeypatch.setattr(provider, "_synthesize_with_windows_sapi", fake_sapi)
    output = tmp_path / "fallback.wav"
    await provider.synthesize_preset("系统语音兜底。", "中文女", output)

    assert output.stat().st_size > 1024
    await provider.close()
