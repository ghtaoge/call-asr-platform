import json
from pathlib import Path
from threading import Lock

from app.core.models import RiskLevel, SensitiveHit, Speaker
from app.sensitive.automaton import SensitiveEntry, SensitiveScanner


class SensitiveStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()
        self._version = "unloaded"
        self._scanner = SensitiveScanner.from_entries([])
        self._tenant_scanners: dict[str, tuple[int, SensitiveScanner]] = {}

    @property
    def version(self) -> str:
        return self._version

    def reload(self) -> str:
        entries = self._load_entries()
        scanner = SensitiveScanner.from_entries(entries)
        version = f"{self._path.name}:{self._path.stat().st_mtime_ns}"
        with self._lock:
            self._scanner = scanner
            self._version = version
        return version

    def scan(self, text: str, speaker: Speaker, segment_id: str, start_ms: int, end_ms: int, tenant_id: str = "default") -> list[SensitiveHit]:
        with self._lock:
            scanner, version = self._tenant_scanners.get(tenant_id, (self._scanner, None))
        hits = scanner.scan(text, speaker, segment_id, start_ms, end_ms)
        if version is not None:
            for hit in hits:
                hit.dictionary_version = version
        return hits

    def replace_tenant(self, tenant_id: str, entries: list[SensitiveEntry], version: int) -> None:
        scanner = SensitiveScanner.from_entries(entries)
        with self._lock:
            self._tenant_scanners[tenant_id] = (version, scanner)

    def _load_entries(self) -> list[SensitiveEntry]:
        raw_items = json.loads(self._path.read_text(encoding="utf-8"))
        return [
            SensitiveEntry(
                word=item["word"],
                level=RiskLevel(item["level"]),
                category=item["category"],
                enabled=bool(item.get("enabled", True)),
            )
            for item in raw_items
        ]
