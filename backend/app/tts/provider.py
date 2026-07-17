from pathlib import Path

import httpx


class TtsProviderError(RuntimeError):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


class CosyVoiceWorkerProvider:
    def __init__(self, base_url: str, token: str | None, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or ""
        # The worker is a local process. Ignoring system proxy variables prevents
        # localhost requests from being redirected to an enterprise HTTP proxy.
        self.client = httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def synthesize(
        self,
        text: str,
        prompt_text: str,
        prompt_path: Path,
        output_path: Path,
    ) -> None:
        try:
            response = await self.client.post(
                f"{self.base_url}/synthesize",
                headers={"X-Worker-Token": self.token},
                json={
                    "text": text,
                    "prompt_text": prompt_text,
                    "prompt_path": str(prompt_path.resolve()),
                    "output_path": str(output_path.resolve()),
                },
            )
        except httpx.HTTPError as exc:
            raise TtsProviderError("worker_unavailable", "CosyVoice 工作进程不可用") from exc
        if response.status_code != 200:
            raise TtsProviderError("synthesis_failed", "语音合成失败")
        if not output_path.is_file() or output_path.stat().st_size <= 44:
            raise TtsProviderError("empty_audio", "语音合成未生成有效音频")

    async def close(self) -> None:
        await self.client.aclose()
