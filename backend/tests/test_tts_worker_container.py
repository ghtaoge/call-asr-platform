from pathlib import Path


def test_worker_image_is_pinned_and_does_not_download_models():
    dockerfile = (Path(__file__).parents[1] / "tts_worker" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04" in dockerfile
    assert "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc" in dockerfile
    assert "snapshot_download" not in dockerfile
    assert "USER app" in dockerfile


def test_worker_has_liveness_and_readiness_routes():
    source = (Path(__file__).parents[1] / "tts_worker" / "server.py").read_text(
        encoding="utf-8"
    )
    assert '"/health/live"' in source
    assert '"/health/ready"' in source
