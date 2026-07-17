import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path


class AudioTooLargeError(ValueError):
    pass


class JobStorage:
    def __init__(self, jobs_dir: Path, retention_days: int, max_bytes: int) -> None:
        self.jobs_dir = jobs_dir.resolve()
        self.retention_days = retention_days
        self.max_bytes = max_bytes
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        if not job_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in job_id
        ):
            raise ValueError("invalid job id")
        path = (self.jobs_dir / job_id).resolve()
        if self.jobs_dir not in path.parents:
            raise ValueError("job path escaped storage root")
        return path

    def save_bytes(self, job_id: str, data: bytes) -> Path:
        if len(data) > self.max_bytes:
            raise AudioTooLargeError("音频文件不能超过 50 MB")
        directory = self.job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        final_path = directory / "source"
        temporary = directory / "source.part"
        try:
            temporary.write_bytes(data)
            os.replace(temporary, final_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return final_path

    def cleanup_expired(self, now: datetime | None = None) -> list[str]:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=self.retention_days)
        removed: list[str] = []
        for directory in self.jobs_dir.iterdir():
            if not directory.is_dir():
                continue
            modified = datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)
            if modified >= cutoff:
                continue
            resolved = directory.resolve()
            if self.jobs_dir not in resolved.parents:
                continue
            shutil.rmtree(resolved)
            removed.append(directory.name)
        return removed
