import os
from datetime import UTC, datetime, timedelta

from app.jobs.storage import JobStorage


def test_job_storage_saves_source_and_removes_expired_jobs(tmp_path):
    storage = JobStorage(tmp_path, retention_days=7, max_bytes=1024)
    path = storage.save_bytes("job_1", b"RIFFdata")
    assert path.read_bytes() == b"RIFFdata"
    old = datetime.now(UTC) - timedelta(days=8)
    os.utime(path.parent, (old.timestamp(), old.timestamp()))
    assert storage.cleanup_expired() == ["job_1"]
