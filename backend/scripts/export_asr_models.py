from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export(source: Path, output: Path, model_id: str, revision: str) -> Path:
    if not source.is_dir():
        raise FileNotFoundError(source)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        relative = path.relative_to(source)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        files.append({"path": relative.as_posix(), "sha256": sha256(destination), "bytes": destination.stat().st_size})
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps({
        "model_id": model_id,
        "source_revision": revision,
        "sample_rate": 16000,
        "chunk_ms": 200,
        "precision": "fp16",
        "export_tool_version": "call-asr-platform-1",
        "files": files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy offline ASR artifacts and write a checksum manifest")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(export(args.source, args.output, args.model_id, args.revision))


if __name__ == "__main__":
    main()
