import asyncio
import base64
import os
import subprocess
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
        self._ensure_audio(output_path)

    async def synthesize_preset(
        self,
        text: str,
        model_speaker: str,
        output_path: Path,
    ) -> None:
        try:
            await self._synthesize_preset_remote(text, model_speaker, output_path)
        except TtsProviderError as exc:
            # Keep the local demo usable when the optional Conda worker is not
            # installed. This fallback only handles voices present in Windows;
            # custom reference voices still require CosyVoice.
            if exc.code != "worker_unavailable" or model_speaker not in {
                "中文女", "中文男", "英文女", "英文男"
            }:
                raise
            await asyncio.to_thread(self._synthesize_with_windows_sapi, text, model_speaker, output_path)

    async def _synthesize_preset_remote(
        self,
        text: str,
        model_speaker: str,
        output_path: Path,
    ) -> None:
        try:
            response = await self.client.post(
                f"{self.base_url}/synthesize",
                headers={"X-Worker-Token": self.token},
                json={
                    "text": text,
                    "preset_speaker": model_speaker,
                    "output_path": str(output_path.resolve()),
                },
            )
        except httpx.HTTPError as exc:
            raise TtsProviderError("worker_unavailable", "CosyVoice 工作进程不可用") from exc
        if response.status_code == 422:
            raise TtsProviderError("preset_unavailable", "所选默认音色不可用")
        if response.status_code != 200:
            raise TtsProviderError("synthesis_failed", "语音合成失败")
        self._ensure_audio(output_path)

    @staticmethod
    def _ensure_audio(output_path: Path) -> None:
        # A RIFF header alone is 44 bytes; reject tiny header-only files too.
        if not output_path.is_file() or output_path.stat().st_size <= 1024:
            raise TtsProviderError("empty_audio", "语音合成未生成有效音频")

    @staticmethod
    def _synthesize_with_windows_sapi(
        text: str,
        model_speaker: str,
        output_path: Path,
    ) -> None:
        if os.name != "nt":
            raise TtsProviderError("worker_unavailable", "CosyVoice 工作进程不可用")
        voice_name = "Microsoft Huihui Desktop - Chinese (Simplified)"
        if model_speaker in {"英文女", "英文男"}:
            voice_name = "Microsoft Zira Desktop - English (United States)"
        script = """
$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__TEXT__'))
$output = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__OUTPUT__'))
$voiceName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__VOICE__'))
$voice = New-Object -ComObject SAPI.SpVoice
$candidate = $voice.GetVoices() | Where-Object { $_.GetDescription() -eq $voiceName } | Select-Object -First 1
if ($null -ne $candidate) { $voice.Voice = $candidate }
$stream = New-Object -ComObject SAPI.SpFileStream
$format = New-Object -ComObject SAPI.SpAudioFormat
$format.Type = 22
$stream.Format = $format
$stream.Open($output, 3, $false)
$voice.AudioOutputStream = $stream
[void]$voice.Speak($text)
$stream.Close()
"""
        values = {
            "__TEXT__": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "__OUTPUT__": base64.b64encode(str(output_path.resolve()).encode("utf-8")).decode("ascii"),
            "__VOICE__": base64.b64encode(voice_name.encode("utf-8")).decode("ascii"),
        }
        for marker, value in values.items():
            script = script.replace(marker, value)
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TtsProviderError("sapi_unavailable", "系统语音合成不可用") from exc
        if result.returncode != 0:
            raise TtsProviderError("sapi_failed", "系统语音合成失败")
        CosyVoiceWorkerProvider._ensure_audio(output_path)

    async def close(self) -> None:
        await self.client.aclose()
