import hashlib
import json

import pytest

from asr_service.engine import ModelArtifactError, validate_manifest


def test_manifest_validates_artifact_hashes(tmp_path):
    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"model")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "files": [{"path": "model.onnx", "sha256": hashlib.sha256(b"model").hexdigest()}]
    }), encoding="utf-8")
    assert validate_manifest(manifest)["files"][0]["path"] == "model.onnx"


def test_manifest_rejects_checksum_mismatch(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"model")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "files": [{"path": "model.onnx", "sha256": "0" * 64}]
    }), encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="checksum"):
        validate_manifest(manifest)
