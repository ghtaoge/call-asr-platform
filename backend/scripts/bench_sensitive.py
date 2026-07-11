import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import RiskLevel, Speaker
from app.sensitive.automaton import SensitiveEntry, SensitiveScanner


def main() -> None:
    entries = [
        SensitiveEntry(word=f"风险词{i}", level=RiskLevel.medium, category="bench")
        for i in range(100_000)
    ]
    started = time.perf_counter()
    scanner = SensitiveScanner.from_entries(entries)
    build_seconds = time.perf_counter() - started

    text = "客户说风险词99999需要关注。" * 1000
    started = time.perf_counter()
    hits = scanner.scan(text, Speaker.customer, "bench_seg", 0, 1000)
    scan_seconds = time.perf_counter() - started

    print(
        {
            "entries": len(entries),
            "hits": len(hits),
            "build_seconds": round(build_seconds, 4),
            "scan_seconds": round(scan_seconds, 4),
            "chars": len(text),
        }
    )


if __name__ == "__main__":
    main()
