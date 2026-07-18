from pathlib import Path

import yaml


def test_compose_assigns_gpu_and_read_only_models():
    path = Path(__file__).parents[2] / "deploy" / "docker-compose.yml"
    compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    worker = compose["services"]["cosyvoice-worker"]
    assert worker["environment"]["CUDA_VISIBLE_DEVICES"] == "${TTS_GPU_DEVICE:-1}"
    assert any(str(volume).endswith(":/models:ro") for volume in worker["volumes"])
    assert worker["restart"] == "unless-stopped"
    assert "healthcheck" in worker
