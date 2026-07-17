import httpx
import pytest

from app.tts.provider import CosyVoiceWorkerProvider, TtsProviderError


class FailingClient:
    async def post(self, *args, **kwargs):
        request = httpx.Request("POST", "http://127.0.0.1:18081/synthesize")
        raise httpx.ConnectError("worker unavailable", request=request)

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
