import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


class DownloadError(RuntimeError):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


@dataclass(frozen=True)
class DownloadedAudio:
    path: Path
    content_type: str
    display_url: str


def _system_resolver(hostname: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(hostname, None)})


class SafeAudioDownloader:
    def __init__(
        self,
        max_bytes: int,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[[str], list[str]] = _system_resolver,
        max_redirects: int = 5,
    ) -> None:
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.transport = transport
        self.resolver = resolver
        self.max_redirects = max_redirects

    def download(self, url: str, destination: Path) -> DownloadedAudio:
        current = self._validate_url(url)
        headers = {
            "Accept": "audio/*,application/octet-stream;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "Call-ASR-Platform/1.0",
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f"{destination.name}.part")
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.transport,
                headers=headers,
            ) as client:
                for redirect_count in range(self.max_redirects + 1):
                    with client.stream("GET", current) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if redirect_count >= self.max_redirects:
                                raise DownloadError("too_many_redirects", "语音地址重定向次数过多")
                            location = response.headers.get("location")
                            if not location:
                                raise DownloadError("download_failed", "语音地址返回了无效重定向")
                            current = self._validate_url(urljoin(current, location))
                            continue
                        try:
                            response.raise_for_status()
                        except httpx.HTTPStatusError as exc:
                            raise DownloadError(
                                "download_failed",
                                f"远程服务器返回 {exc.response.status_code}",
                            ) from exc
                        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                        if content_type and not (
                            content_type.startswith("audio/")
                            or content_type in {"application/octet-stream", "binary/octet-stream"}
                        ):
                            raise DownloadError("invalid_audio", "URL 返回的内容不是音频文件")
                        total = 0
                        with temporary.open("wb") as output:
                            for chunk in response.iter_bytes():
                                total += len(chunk)
                                if total > self.max_bytes:
                                    raise DownloadError("audio_too_large", "音频文件不能超过 50 MB")
                                output.write(chunk)
                        if total == 0:
                            raise DownloadError("invalid_audio", "URL 返回了空音频文件")
                        os.replace(temporary, destination)
                        return DownloadedAudio(
                            path=destination,
                            content_type=content_type or "application/octet-stream",
                            display_url=self._display_url(current),
                        )
        except DownloadError:
            temporary.unlink(missing_ok=True)
            raise
        except httpx.TimeoutException as exc:
            temporary.unlink(missing_ok=True)
            raise DownloadError("download_timeout", "下载语音文件超时") from exc
        except httpx.HTTPError as exc:
            temporary.unlink(missing_ok=True)
            raise DownloadError("download_failed", "无法下载语音文件") from exc
        temporary.unlink(missing_ok=True)
        raise DownloadError("download_failed", "无法下载语音文件")

    def _validate_url(self, url: str) -> str:
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise DownloadError("invalid_url", "语音 URL 格式不合法") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DownloadError("invalid_url", "语音 URL 必须以 http:// 或 https:// 开头")
        if parsed.username or parsed.password:
            raise DownloadError("invalid_url", "语音 URL 不能包含用户名或密码")
        try:
            literal_ip = ipaddress.ip_address(parsed.hostname)
            addresses = [str(literal_ip)]
        except ValueError:
            try:
                addresses = self.resolver(parsed.hostname)
            except OSError as exc:
                raise DownloadError("download_failed", "无法解析语音服务器地址") from exc
        if not addresses:
            raise DownloadError("download_failed", "无法解析语音服务器地址")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise DownloadError("blocked_url", "语音 URL 指向了不安全的地址") from exc
            if not ip.is_global:
                raise DownloadError("blocked_url", "语音 URL 不能访问本机或内网地址")
        return urlunsplit(parsed)

    @staticmethod
    def _display_url(url: str) -> str:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
