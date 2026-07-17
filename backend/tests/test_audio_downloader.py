import httpx
import pytest

from app.audio.downloader import DownloadError, SafeAudioDownloader


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/audio.wav",
        "http://169.254.169.254/latest/meta-data",
        "http://user:pass@example.com/audio.wav",
    ],
)
def test_downloader_rejects_unsafe_urls(url, tmp_path):
    downloader = SafeAudioDownloader(max_bytes=1024, timeout=2)
    with pytest.raises(DownloadError) as exc:
        downloader.download(url, tmp_path / "source")
    assert exc.value.code in {"blocked_url", "invalid_url"}


def test_downloader_validates_redirect_targets(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    downloader = SafeAudioDownloader(
        max_bytes=1024,
        timeout=2,
        transport=httpx.MockTransport(handler),
        resolver=lambda host: ["93.184.216.34"],
    )
    with pytest.raises(DownloadError) as exc:
        downloader.download("https://example.com/start", tmp_path / "source")
    assert exc.value.code == "blocked_url"


def test_downloader_streams_valid_audio_and_removes_query_from_display_url(tmp_path):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=b"RIFFaudio",
            headers={"content-type": "audio/wav"},
        )
    )
    downloader = SafeAudioDownloader(
        max_bytes=1024,
        timeout=2,
        transport=transport,
        resolver=lambda host: ["93.184.216.34"],
    )
    result = downloader.download(
        "https://example.com/call.wav?token=secret",
        tmp_path / "source",
    )
    assert result.path.read_bytes() == b"RIFFaudio"
    assert result.display_url == "https://example.com/call.wav"
