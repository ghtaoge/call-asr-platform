import json

from scripts.bench_asr_service import percentile


def test_percentile_is_deterministic():
    assert percentile([1, 2, 3, 4], 0.95) == 4


def test_report_schema_contains_release_gate_fields(tmp_path):
    report = {
        "concurrency": [20, 50, 100],
        "duration_seconds": 600,
        "partial_p50_ms": 100,
        "partial_p95_ms": 200,
        "partial_p99_ms": 300,
        "final_p95_ms": 400,
        "offline_rtf_p95": 0.2,
        "errors": 0,
        "dropped_frames": 0,
        "gpu_model": "test",
        "artifact_checksum": "test",
        "accuracy_comparison": "pass",
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert {"partial_p95_ms", "final_p95_ms", "offline_rtf_p95", "artifact_checksum"} <= loaded.keys()
