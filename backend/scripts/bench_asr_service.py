from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grpc

from app.asr_rpc.generated import asr_pb2, asr_pb2_grpc


@dataclass
class StreamMeasurement:
    partial_ms: list[float]
    final_ms: float | None
    errors: int


async def run_stream(stub, duration: float) -> StreamMeasurement:
    started = time.perf_counter()
    first_partial = None
    final = None
    errors = 0

    async def requests():
        sequence = 0
        end_at = time.perf_counter() + duration
        while time.perf_counter() < end_at:
            yield asr_pb2.AudioFrame(
                tenant_id="benchmark",
                call_id=f"bench-{id(asyncio.current_task())}",
                stream_id="stream",
                speaker="unknown",
                sequence=sequence,
                captured_at_ms=sequence * 20,
                pcm_s16le=b"\0\0" * 320,
            )
            sequence += 1
            await asyncio.sleep(0.02)
        yield asr_pb2.AudioFrame(
            tenant_id="benchmark", call_id=f"bench-{id(asyncio.current_task())}", stream_id="stream",
            speaker="unknown", sequence=sequence, captured_at_ms=sequence * 20, end_of_stream=True,
        )

    try:
        async for event in stub.StreamRecognize(requests()):
            if event.type in {"partial_transcript", "final_transcript"}:
                elapsed = (time.perf_counter() - started) * 1000
                if event.type == "partial_transcript" and first_partial is None:
                    first_partial = elapsed
                if event.type == "final_transcript":
                    final = elapsed
    except Exception:
        errors += 1
    return StreamMeasurement(([first_partial] if first_partial is not None else []), final, errors)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, round((len(values) - 1) * p))
    return round(values[index], 2)


async def benchmark(target: str, concurrency: list[int], duration: float) -> dict:
    channel = grpc.aio.insecure_channel(target)
    stub = asr_pb2_grpc.AsrServiceStub(channel)
    health = await stub.Check(asr_pb2.HealthRequest(), timeout=10)
    report = {
        "target": target,
        "concurrency": concurrency,
        "duration_seconds": duration,
        "partial_p50_ms": 0.0,
        "partial_p95_ms": 0.0,
        "partial_p99_ms": 0.0,
        "final_p95_ms": 0.0,
        "offline_rtf_p95": None,
        "errors": 0,
        "dropped_frames": 0,
        "gpu_model": "reported-by-deployment",
        "artifact_checksum": health.artifact_checksum,
        "accuracy_comparison": "not-run",
    }
    all_partial: list[float] = []
    all_final: list[float] = []
    for level in concurrency:
        measurements = await asyncio.gather(*(run_stream(stub, duration) for _ in range(level)))
        all_partial.extend(value for item in measurements for value in item.partial_ms)
        all_final.extend(item.final_ms for item in measurements if item.final_ms is not None)
        report["errors"] += sum(item.errors for item in measurements)
    report["partial_p50_ms"] = percentile(all_partial, 0.50)
    report["partial_p95_ms"] = percentile(all_partial, 0.95)
    report["partial_p99_ms"] = percentile(all_partial, 0.99)
    report["final_p95_ms"] = percentile(all_final, 0.95)
    await channel.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="127.0.0.1:50051")
    parser.add_argument("--concurrency", default="20,50,100")
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(benchmark(args.target, [int(item) for item in args.concurrency.split(",")], args.duration))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.enforce and (report["errors"] or report["dropped_frames"] or report["partial_p95_ms"] > 800):
        raise SystemExit("ASR benchmark gate failed")


if __name__ == "__main__":
    main()
