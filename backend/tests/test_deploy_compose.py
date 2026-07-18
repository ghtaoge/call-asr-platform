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


def test_compose_isolates_realtime_and_batch_asr_services():
    path = Path(__file__).parents[2] / "deploy" / "docker-compose.yml"
    compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["asr-realtime"]["environment"]["CUDA_VISIBLE_DEVICES"] == "${ASR_REALTIME_GPU_DEVICE:-0}"
    assert services["asr-batch"]["environment"]["CUDA_VISIBLE_DEVICES"] == "${ASR_BATCH_GPU_DEVICE:-1}"
    assert any(str(volume).endswith(":/models:ro") for volume in services["asr-realtime"]["volumes"])
    assert services["backend"]["environment"]["CALL_ASR_ASR_REALTIME_TARGET"] == "asr-realtime:50051"
    assert services["backend"]["environment"]["CALL_ASR_ASR_BATCH_TARGET"] == "asr-batch:50052"
