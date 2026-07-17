import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse


RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


def audio_file_response(
    path: Path,
    media_type: str,
    range_header: str | None = None,
    download_name: str | None = None,
    extra_headers: dict[str, str] | None = None,
):
    headers = {"Accept-Ranges": "bytes", **(extra_headers or {})}
    if not range_header:
        return FileResponse(
            path,
            media_type=media_type,
            filename=download_name,
            headers=headers,
        )
    start, end = _parse_range(range_header, path.stat().st_size)
    length = end - start + 1
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{path.stat().st_size}",
        "Content-Length": str(length),
    })
    return StreamingResponse(
        _file_range(path, start, length),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


def _parse_range(value: str, size: int) -> tuple[int, int]:
    match = RANGE_PATTERN.fullmatch(value.strip())
    if not match or size <= 0:
        raise HTTPException(status_code=416, detail="无效的音频范围")
    raw_start, raw_end = match.groups()
    if not raw_start and not raw_end:
        raise HTTPException(status_code=416, detail="无效的音频范围")
    if not raw_start:
        suffix = int(raw_end)
        if suffix <= 0:
            raise HTTPException(status_code=416, detail="无效的音频范围")
        start, end = max(0, size - suffix), size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
    if start >= size or end < start:
        raise HTTPException(status_code=416, detail="无效的音频范围")
    return start, min(end, size - 1)


def _file_range(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as source:
        source.seek(start)
        while remaining:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
