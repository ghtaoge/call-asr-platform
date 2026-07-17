# ASR Inference Service and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move realtime and offline ASR out of the FastAPI process, support 100 concurrent streaming sessions on GPU 0 with P95 subtitle latency below 800ms, and reduce offline P95 RTF below 0.3 on GPU 1.

**Architecture:** Define one internal gRPC protocol used by browser and future SIPREC adapters. A dedicated realtime service aggregates 20ms frames into 200ms chunks and schedules deadline-aware microbatches; a separate batch service performs VAD-first batched transcription. Both load pre-exported model artifacts at startup and expose readiness only after warmup.

**Tech Stack:** Python 3.11, grpc.aio, protobuf, NumPy, ONNX Runtime GPU/TensorRT, FunASR model artifacts, Prometheus, pytest, Docker Compose, NVIDIA GPU

---

## File Map

- Create `proto/asr.proto`: internal streaming and batch RPC contract.
- Create `backend/app/asr_rpc/generated/`: generated Python stubs.
- Create `backend/app/asr_rpc/client.py`: business-backend gRPC client.
- Create `backend/asr_service/config.py`: model, batching, deadline, and device settings.
- Create `backend/asr_service/session.py`: per-call sequence, PCM buffer, caches, and timestamps.
- Create `backend/asr_service/scheduler.py`: deadline-aware dynamic batching.
- Create `backend/asr_service/engine.py`: realtime engine protocol and ONNX implementation.
- Create `backend/asr_service/server.py`: gRPC methods, health, metrics, and lifecycle.
- Create `backend/asr_service/batch_engine.py`: VAD-first offline batching.
- Create `backend/scripts/export_asr_models.py`: reproducible artifact export and manifest.
- Create `backend/scripts/bench_asr_service.py`: 20/50/100-session benchmark.
- Modify `backend/app/realtime/manager.py`: replace local executor with gRPC client.
- Modify `backend/app/jobs/manager.py`: call batch RPC instead of local ASR execution.
- Modify `backend/app/main.py`: initialize clients and remove model ownership from API process.
- Modify `deploy/docker-compose.yml`: GPU 0 realtime service and GPU 1 batch service.
- Create focused tests under `backend/tests/asr_service/`.
- Modify `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, and `docs/API.md`.

## Task 1: Define Versioned Internal gRPC Protocol

**Files:**
- Create: `proto/asr.proto`
- Create: `backend/tests/asr_service/test_proto_contract.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Write failing protocol contract test**

```python
from pathlib import Path


def test_asr_proto_contains_streaming_sequence_and_batch_rpc():
    source = Path("../proto/asr.proto").read_text(encoding="utf-8")
    assert "rpc StreamRecognize(stream AudioFrame) returns (stream RecognitionEvent)" in source
    assert "uint64 sequence = 5" in source
    assert "rpc BatchRecognize(BatchRequest) returns (BatchResponse)" in source
```

- [ ] **Step 2: Run and verify failure**

Run: `cd backend; python -m pytest tests/asr_service/test_proto_contract.py -q`

Expected: FAIL because the proto file does not exist.

- [ ] **Step 3: Create protocol**

```proto
syntax = "proto3";
package callasr.v1;

service AsrService {
  rpc StreamRecognize(stream AudioFrame) returns (stream RecognitionEvent);
  rpc BatchRecognize(BatchRequest) returns (BatchResponse);
}

message AudioFrame {
  string tenant_id = 1;
  string call_id = 2;
  string stream_id = 3;
  string speaker = 4;
  uint64 sequence = 5;
  uint64 captured_at_ms = 6;
  bytes pcm_s16le = 7;
  bool end_of_stream = 8;
}

message RecognitionEvent {
  string call_id = 1;
  string stream_id = 2;
  string type = 3;
  uint64 ack_sequence = 4;
  int64 start_ms = 5;
  int64 end_ms = 6;
  string text = 7;
  bool is_final = 8;
  string error_code = 9;
}

message BatchRequest { string tenant_id = 1; string job_id = 2; repeated BatchChannel channels = 3; }
message BatchChannel { string speaker = 1; bytes wav = 2; }
message BatchSegment { string speaker = 1; int64 start_ms = 2; int64 end_ms = 3; string text = 4; float confidence = 5; }
message BatchResponse { repeated BatchSegment segments = 1; string model_version = 2; }
```

Add `grpcio`, `grpcio-tools`, `protobuf`, `prometheus-client`, and `onnxruntime-gpu` to the service dependency group. Generate stubs with a checked script and commit generated files so production images do not compile protobuf at startup.

- [ ] **Step 4: Generate and test contract**

Run:

```powershell
python -m grpc_tools.protoc -I ../proto --python_out app/asr_rpc/generated --grpc_python_out app/asr_rpc/generated ../proto/asr.proto
python -m pytest tests/asr_service/test_proto_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add proto backend/app/asr_rpc backend/pyproject.toml backend/tests/asr_service/test_proto_contract.py
git commit -m "feat: define internal ASR gRPC protocol"
```

## Task 2: Build Per-Session Aggregation and Sequence State

**Files:**
- Create: `backend/asr_service/session.py`
- Test: `backend/tests/asr_service/test_session.py`

- [ ] **Step 1: Write failing aggregation tests**

```python
def test_session_aggregates_ten_20ms_frames_into_200ms_chunk():
    session = StreamingSessionState("call", "stream", sample_rate=16000, chunk_ms=200)
    chunks = []
    for sequence in range(10):
        chunks.extend(session.push(sequence, sequence * 20, b"\0\0" * 320))
    assert len(chunks) == 1
    assert chunks[0].first_sequence == 0
    assert chunks[0].last_sequence == 9
    assert len(chunks[0].pcm) == 6400


def test_session_rejects_duplicate_and_gap_larger_than_window():
    session = StreamingSessionState("call", "stream", 16000, 200)
    session.push(0, 0, b"\0\0" * 320)
    assert session.push(0, 0, b"\0\0" * 320) == []
    with pytest.raises(SequenceGapError):
        session.push(600, 12000, b"\0\0" * 320)
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/asr_service/test_session.py -q`

Expected: FAIL because session state does not exist.

- [ ] **Step 3: Implement bounded aggregation**

Create immutable `InferenceChunk(first_sequence, last_sequence, captured_at_ms, pcm, is_final)` and `StreamingSessionState`. Validate 16-bit alignment, maximum 4096-byte frame, monotonic sequence, bounded reorder window, and maximum buffered audio. Aggregate exactly `chunk_ms` except final flush. Maintain separate `asr_cache`, `vad_cache`, current text, sentence start sample, and last activity monotonic time.

- [ ] **Step 4: Run session tests**

Run: `python -m pytest tests/asr_service/test_session.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/asr_service/session.py backend/tests/asr_service/test_session.py
git commit -m "feat: aggregate realtime ASR frames per session"
```

## Task 3: Implement Deadline-Aware Microbatch Scheduler

**Files:**
- Create: `backend/asr_service/scheduler.py`
- Test: `backend/tests/asr_service/test_scheduler.py`

- [ ] **Step 1: Write failing scheduler tests**

```python
async def test_scheduler_batches_sessions_without_missing_deadline(fake_engine):
    clock = FakeClock()
    scheduler = BatchScheduler(fake_engine, clock, max_batch=16, tick_ms=40, max_wait_ms=120)
    await scheduler.submit(chunk("a", captured_at=0))
    await scheduler.submit(chunk("b", captured_at=10))
    clock.advance(40)
    await scheduler.tick()
    assert fake_engine.batch_session_ids == [["a", "b"]]


async def test_oldest_chunk_flushes_before_batch_is_full(fake_engine):
    scheduler = BatchScheduler(fake_engine, FakeClock(now_ms=121), 16, 40, 120)
    await scheduler.submit(chunk("a", captured_at=0))
    await scheduler.tick()
    assert fake_engine.batch_session_ids == [["a"]]
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/asr_service/test_scheduler.py -q`

Expected: FAIL because `BatchScheduler` does not exist.

- [ ] **Step 3: Implement scheduler**

Use one bounded `asyncio.Queue` per priority class. Never place two chunks from the same session in one batch. Flush when `max_batch` is reached or oldest wait exceeds `max_wait_ms`. Return a future per submitted chunk. Export queue wait, batch size, inference duration, rejected chunks, and deadline misses as Prometheus metrics.

- [ ] **Step 4: Run scheduler tests**

Run: `python -m pytest tests/asr_service/test_scheduler.py -q`

Expected: PASS including cancellation and queue-full cases.

- [ ] **Step 5: Commit**

```powershell
git add backend/asr_service/scheduler.py backend/tests/asr_service/test_scheduler.py
git commit -m "feat: schedule realtime ASR microbatches"
```

## Task 4: Add Warmed Model Engine and Artifact Manifest

**Files:**
- Create: `backend/asr_service/engine.py`
- Create: `backend/asr_service/config.py`
- Create: `backend/scripts/export_asr_models.py`
- Test: `backend/tests/asr_service/test_engine.py`

- [ ] **Step 1: Write failing manifest and warmup tests**

```python
def test_engine_rejects_manifest_checksum_mismatch(tmp_path):
    manifest = write_manifest(tmp_path, sha256="0" * 64)
    with pytest.raises(ModelArtifactError, match="checksum"):
        OnnxStreamingEngine.from_manifest(manifest, device_id=0)


async def test_engine_is_not_ready_before_warmup(fake_runtime):
    engine = OnnxStreamingEngine(fake_runtime)
    assert not engine.ready
    await engine.warmup()
    assert engine.ready
    assert fake_runtime.calls == 3
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/asr_service/test_engine.py -q`

Expected: FAIL because the engine and manifest do not exist.

- [ ] **Step 3: Implement engine boundary**

Define `StreamingEngine.infer_batch(chunks, caches) -> list[EngineResult]`. Load ONNX sessions with CUDA provider, FP16 artifacts, explicit GPU device, bounded CUDA arena, and no online model downloads. Manifest fields are model ID, upstream revision, files with SHA-256, sample rate, chunk configuration, export tool version, and precision. Warmup with silence and speech-like tensors three times before setting ready.

`export_asr_models.py` accepts an offline source directory and output directory, exports streaming Paraformer and VAD, computes hashes, and writes `manifest.json`; it must record model ID `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online`, source revision `master`, and every source/output SHA-256. The released artifact is identified by the manifest checksum rather than by mutable remote state.

- [ ] **Step 4: Run tests and offline export smoke**

Run:

```powershell
python -m pytest tests/asr_service/test_engine.py -q
python scripts/export_asr_models.py --source D:\models\speech_paraformer_online --output D:\artifacts\asr-realtime --model-id iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online --revision master
```

Expected: tests PASS and manifest contains no absolute source paths.

- [ ] **Step 5: Commit**

```powershell
git add backend/asr_service/engine.py backend/asr_service/config.py backend/scripts/export_asr_models.py backend/tests/asr_service/test_engine.py
git commit -m "feat: load warmed ASR inference artifacts"
```

## Task 5: Expose Streaming gRPC Service

**Files:**
- Create: `backend/asr_service/server.py`
- Test: `backend/tests/asr_service/test_server.py`

- [ ] **Step 1: Write failing in-process gRPC test**

```python
async def test_stream_returns_ack_partial_and_final(asr_stub, fake_engine):
    events = [event async for event in asr_stub.StreamRecognize(frame_stream(20))]
    assert max(event.ack_sequence for event in events) == 19
    assert any(event.type == "partial_transcript" for event in events)
    final = next(event for event in events if event.is_final)
    assert final.start_ms == 0
    assert final.end_ms > final.start_ms
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/asr_service/test_server.py -q`

Expected: FAIL because the service is not implemented.

- [ ] **Step 3: Implement stream lifecycle**

Create one `StreamingSessionState` per `(tenant_id, call_id, stream_id)`. Validate consistent identity and speaker for the stream. Submit aggregated chunks to the scheduler, emit acknowledgement after inference accepts a chunk, emit partial text at most every 300ms, and final text immediately on endpoint. On cancellation, flush only when `end_of_stream` was received; otherwise retain session for the configured reconnect grace period. Reject queue overflow with `RESOURCE_EXHAUSTED` and a stable error detail.

- [ ] **Step 4: Run server tests**

Run: `python -m pytest tests/asr_service/test_server.py -q`

Expected: PASS including reconnect, timeout, queue-full, and isolation tests.

- [ ] **Step 5: Commit**

```powershell
git add backend/asr_service/server.py backend/tests/asr_service/test_server.py
git commit -m "feat: serve streaming ASR over gRPC"
```

## Task 6: Migrate Browser Realtime Manager to gRPC

**Files:**
- Create: `backend/app/asr_rpc/client.py`
- Modify: `backend/app/realtime/manager.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_realtime_api.py`
- Test: `backend/tests/test_realtime_session.py`

- [ ] **Step 1: Write failing adapter test**

```python
async def test_browser_frames_are_forwarded_to_asr_rpc(manager, rpc):
    await manager.control("call", {"type": "start_session", "codec": "pcm_s16le", "sample_rate": 16000})
    events = await manager.accept("call", encoded_frame(sequence=7))
    assert rpc.frames[0].sequence == 7
    assert any(event["type"] == "audio_ack" for event in events)
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/test_realtime_api.py tests/test_realtime_session.py -q`

Expected: FAIL because the manager still owns local models.

- [ ] **Step 3: Implement adapter and remove local inference ownership**

`AsrRpcClient` opens one bidi stream per browser session, maps the existing 16-byte frame protocol to `AudioFrame`, and maps gRPC recognition events back to current WebSocket JSON. Keep browser CAM++ clustering after final segments; remove `ThreadPoolExecutor(max_workers=1)`, streaming model loader, and per-session VAD from `RealtimeManager`. Add channel readiness on application startup and close it during shutdown.

- [ ] **Step 4: Run realtime regression tests**

Run: `python -m pytest tests/test_realtime_api.py tests/test_realtime_session.py -q`

Expected: PASS with no local model creation.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/asr_rpc/client.py backend/app/realtime/manager.py backend/app/main.py backend/app/core/config.py backend/tests/test_realtime_api.py backend/tests/test_realtime_session.py
git commit -m "refactor: route browser realtime audio through ASR service"
```

## Task 7: Add VAD-First Batch Recognition

**Files:**
- Create: `backend/asr_service/batch_engine.py`
- Modify: `backend/asr_service/server.py`
- Modify: `backend/app/jobs/manager.py`
- Test: `backend/tests/asr_service/test_batch_engine.py`
- Test: `backend/tests/test_job_manager.py`

- [ ] **Step 1: Write failing batch tests**

```python
async def test_batch_engine_groups_vad_segments_and_preserves_offsets(engine):
    response = await engine.recognize([channel("sales", wav_with_two_utterances())])
    assert len(response.segments) == 2
    assert response.segments[1].start_ms >= response.segments[0].end_ms
    assert engine.runtime.batch_sizes[-1] == 2


async def test_job_manager_publishes_transcript_before_post_analysis(manager, rpc):
    rpc.batch_response = response_with_segments()
    job = await manager.create_upload(stereo_wav(), "audio/wav")
    await manager.wait_for_transcript(job.job_id)
    assert (await manager.get_result(job.job_id)).segments
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/asr_service/test_batch_engine.py tests/test_job_manager.py -q`

Expected: FAIL because batch RPC is not wired.

- [ ] **Step 3: Implement offline batching**

Decode channels in the business backend exactly once, send mono WAV channels to `BatchRecognize`, VAD-split each channel, sort chunks by duration, infer in bounded batches, restore original offsets, punctuate final text, and return sorted segments. Preserve the existing transcript-first module states. Apply a per-request audio size and duration limit at the RPC boundary.

- [ ] **Step 4: Run batch and job tests**

Run: `python -m pytest tests/asr_service/test_batch_engine.py tests/test_job_manager.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/asr_service/batch_engine.py backend/asr_service/server.py backend/app/jobs/manager.py backend/tests/asr_service/test_batch_engine.py backend/tests/test_job_manager.py
git commit -m "perf: batch offline ASR segments"
```

## Task 8: Deploy GPU-Isolated ASR Services

**Files:**
- Create: `backend/asr_service/Dockerfile`
- Modify: `deploy/docker-compose.yml`
- Test: `backend/tests/test_deploy_compose.py`

- [ ] **Step 1: Extend failing deployment test**

Assert Compose has `asr-realtime` with GPU 0, `asr-batch` with GPU 1, read-only artifact mounts, readiness checks, bounded logs, no public ports, and the backend points to service DNS names.

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/test_deploy_compose.py -q`

Expected: FAIL because ASR services are absent.

- [ ] **Step 3: Add image and Compose services**

Build one ASR image with two commands. Mount `/models:ro`, set `CUDA_VISIBLE_DEVICES=0` for realtime and `1` for batch, use separate gRPC ports, and set memory/queue settings explicitly. Health checks must call gRPC health, not only test the TCP port.

- [ ] **Step 4: Validate deployment**

Run: `docker compose -f deploy/docker-compose.yml config` and the Compose test.

Expected: both PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/asr_service/Dockerfile deploy/docker-compose.yml backend/tests/test_deploy_compose.py
git commit -m "ops: isolate realtime and batch ASR GPUs"
```

## Task 9: Benchmark and Gate Release

**Files:**
- Create: `backend/scripts/bench_asr_service.py`
- Create: `backend/tests/asr_service/test_benchmark_report.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`

- [ ] **Step 1: Define report validation test**

Require JSON report fields for concurrency, duration, partial P50/P95/P99, final P95, RTF P95, errors, dropped frames, GPU model, artifact checksum, and accuracy comparison.

- [ ] **Step 2: Implement benchmark client**

Replay fixed authorized PCM fixtures in wall-clock time for 20, 50, and 100 streams; run offline fixtures separately; collect Prometheus snapshots and write deterministic JSON. Exit nonzero when P95 realtime exceeds 800ms, offline RTF exceeds 0.3, errors/drops are nonzero, or character accuracy falls more than 1% from the checked baseline.

- [ ] **Step 3: Run automated tests and production benchmark**

Run full backend/frontend tests and build, then:

`python scripts/bench_asr_service.py --target asr-realtime:50051 --concurrency 20,50,100 --duration 600 --report output/asr-benchmark.json`

Expected: command exits 0 and report meets every gate.

- [ ] **Step 4: Document capacity and rollback**

Document exact artifact checksums, GPU/driver versions, measured limits, queue configuration, dashboards, alerts, and rollback to the previous API-local inference path behind a temporary feature flag.

- [ ] **Step 5: Commit**

```powershell
git add backend/scripts/bench_asr_service.py backend/tests/asr_service/test_benchmark_report.py docs/ARCHITECTURE.md docs/DEPLOYMENT.md
git commit -m "perf: add ASR capacity release gate"
```

## Completion Criteria

- FastAPI owns no realtime or offline ASR model instance.
- Realtime and batch services are ready only after checksum validation and warmup.
- Browser realtime remains protocol-compatible and SIPREC can reuse the same gRPC stream.
- 100-stream P95 partial latency is below 800ms with no dropped audio.
- Offline P95 RTF is below 0.3 and baseline accuracy degradation is at most 1%.
- GPU 0 serves realtime only; GPU 1 serves batch analysis and coordinated TTS.
- Unit, gRPC integration, job regression, deployment, browser, and benchmark gates pass.
