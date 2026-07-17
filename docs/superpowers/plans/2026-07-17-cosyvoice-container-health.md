# CosyVoice Container and Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run CosyVoice as a reproducible Linux GPU container, expose readiness to the application and UI, and retain queued synthesis jobs across temporary worker outages.

**Architecture:** Keep the current FastAPI TTS API and persistent job metadata, replace the localhost/Conda assumption with a Docker service and a Redis Streams queue. A dispatcher consumes synthesis jobs, waits for worker readiness, retries transient failures without losing the job, and exposes a cached health state to Vue.

**Tech Stack:** Python 3.11, FastAPI, httpx, redis-py asyncio, SQLite transition repository, Vue 3, Vitest, Docker Compose, NVIDIA Container Toolkit, CosyVoice Python 3.10

---

## Dependency and File Map

- Create `backend/app/tts/health.py`: stable health states and readiness cache.
- Create `backend/app/tts/queue.py`: Redis Streams producer/consumer boundary.
- Create `backend/tests/test_tts_health.py`: readiness and public error tests.
- Create `backend/tests/test_tts_queue.py`: enqueue, reclaim, retry, and acknowledgement tests.
- Modify `backend/app/tts/provider.py`: worker health request and transient error classification.
- Modify `backend/app/tts/models.py`: health response, attempt count, and retry timestamp.
- Modify `backend/app/tts/repository.py`: in-place job schema migration and retry persistence.
- Modify `backend/app/tts/manager.py`: dispatch Redis jobs and pause while worker is unavailable.
- Modify `backend/app/api/tts.py`: `GET /api/tts/health` and readiness guard.
- Modify `backend/app/core/config.py`: Redis, worker health, and retry settings.
- Modify `backend/app/main.py`: initialize queue, health monitor, and clean shutdown.
- Modify `backend/pyproject.toml`: add `redis` runtime dependency.
- Create `backend/tts_worker/requirements.lock.txt`: pinned worker-only dependencies.
- Create `backend/tts_worker/Dockerfile`: Python 3.10 CUDA worker image.
- Modify `backend/tts_worker/server.py`: startup loading, smoke test, liveness, and readiness.
- Create `deploy/docker-compose.yml`: app dependencies and GPU assignment.
- Create `deploy/.env.example`: non-secret deployment configuration.
- Modify `frontend/src/types.ts`: TTS health types.
- Modify `frontend/src/api/client.ts`: health request.
- Modify `frontend/src/composables/useTts.ts`: health polling and disabled state.
- Modify `frontend/src/components/TtsPanel.vue`: starting/ready/busy/unavailable states.
- Modify `frontend/src/components/TtsPanel.spec.ts`: health-state UI tests.
- Modify `README.md` and `docs/DEPLOYMENT.md`: model preparation, startup, and diagnostics.

## Task 1: Define TTS Health Contract

**Files:**
- Create: `backend/app/tts/health.py`
- Modify: `backend/app/tts/models.py`
- Test: `backend/tests/test_tts_health.py`

- [ ] **Step 1: Write failing health model tests**

```python
from app.tts.health import TtsHealthCache
from app.tts.models import TtsHealthStatus


def test_health_cache_starts_unavailable_and_tracks_worker_state():
    cache = TtsHealthCache()
    assert cache.snapshot().status == TtsHealthStatus.starting
    cache.mark_ready("Fun-CosyVoice3-0.5B-2512", queue_depth=3)
    value = cache.snapshot()
    assert value.status == TtsHealthStatus.busy
    assert value.queue_depth == 3
    cache.mark_unavailable("worker_connection_failed", "语音合成服务暂不可用")
    assert cache.snapshot().error_code == "worker_connection_failed"
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd backend; python -m pytest tests/test_tts_health.py -q`

Expected: FAIL because `TtsHealthCache` and `TtsHealthStatus` do not exist.

- [ ] **Step 3: Implement stable public health types**

```python
# backend/app/tts/models.py
class TtsHealthStatus(StrEnum):
    starting = "starting"
    ready = "ready"
    busy = "busy"
    unavailable = "unavailable"


class TtsHealthResponse(BaseModel):
    status: TtsHealthStatus
    model: str | None = None
    queue_depth: int = 0
    error_code: str | None = None
    message: str
    checked_at: datetime
```

```python
# backend/app/tts/health.py
from datetime import UTC, datetime
from threading import Lock

from app.tts.models import TtsHealthResponse, TtsHealthStatus


class TtsHealthCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._value = TtsHealthResponse(
            status=TtsHealthStatus.starting,
            message="语音合成模型正在启动",
            checked_at=datetime.now(UTC),
        )

    def snapshot(self) -> TtsHealthResponse:
        with self._lock:
            return self._value.model_copy(deep=True)

    def mark_ready(self, model: str, queue_depth: int) -> None:
        status = TtsHealthStatus.busy if queue_depth else TtsHealthStatus.ready
        with self._lock:
            self._value = TtsHealthResponse(
                status=status, model=model, queue_depth=queue_depth,
                message="任务较多，已进入队列" if queue_depth else "语音合成服务可用",
                checked_at=datetime.now(UTC),
            )

    def mark_unavailable(self, code: str, message: str) -> None:
        with self._lock:
            self._value = TtsHealthResponse(
                status=TtsHealthStatus.unavailable,
                error_code=code, message=message, checked_at=datetime.now(UTC),
            )
```

- [ ] **Step 4: Run the test and verify pass**

Run: `python -m pytest tests/test_tts_health.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/tts/health.py backend/app/tts/models.py backend/tests/test_tts_health.py
git commit -m "feat: define TTS worker health contract"
```

## Task 2: Add Worker Health Monitoring

**Files:**
- Modify: `backend/app/tts/provider.py`
- Modify: `backend/app/tts/manager.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_tts_provider.py`

- [ ] **Step 1: Add failing provider health tests**

```python
async def test_provider_health_uses_worker_token(monkeypatch):
    client = RecordingClient(response_json={"status": "ready", "model": "cosy"})
    monkeypatch.setattr("app.tts.provider.httpx.AsyncClient", lambda **_: client)
    provider = CosyVoiceWorkerProvider("http://worker:18081", "secret", timeout=10)
    result = await provider.health()
    assert result == {"status": "ready", "model": "cosy"}
    assert client.headers["X-Worker-Token"] == "secret"


async def test_provider_health_maps_connection_failure(monkeypatch):
    monkeypatch.setattr("app.tts.provider.httpx.AsyncClient", lambda **_: FailingClient())
    provider = CosyVoiceWorkerProvider("http://worker:18081", "secret", timeout=10)
    with pytest.raises(TtsProviderError) as raised:
        await provider.health()
    assert raised.value.code == "worker_unavailable"
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/test_tts_provider.py -q`

Expected: FAIL because `health()` does not exist.

- [ ] **Step 3: Implement health request and monitor loop**

```python
# backend/app/tts/provider.py
async def health(self) -> dict[str, object]:
    try:
        response = await self.client.get(
            f"{self.base_url}/health/ready",
            headers={"X-Worker-Token": self.token},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise TtsProviderError("worker_unavailable", "语音合成服务暂不可用") from exc
    if response.status_code != 200:
        raise TtsProviderError("worker_not_ready", "语音合成模型正在启动")
    return response.json()
```

Add `health_check_seconds: float = 5.0` and `worker_startup_grace_seconds: float = 300.0` to `Settings`. Add a `TtsManager._monitor_health()` task that calls `provider.health()`, reads queue depth, updates `TtsHealthCache`, sleeps with `asyncio.wait_for(self._closing.wait(), timeout=interval)`, and exits cleanly at shutdown.

- [ ] **Step 4: Run provider and manager tests**

Run: `python -m pytest tests/test_tts_provider.py tests/test_tts_manager.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/tts/provider.py backend/app/tts/manager.py backend/app/core/config.py backend/tests/test_tts_provider.py backend/tests/test_tts_manager.py
git commit -m "feat: monitor CosyVoice readiness"
```

## Task 3: Persist Redis Stream Queue

**Files:**
- Create: `backend/app/tts/queue.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/tts/manager.py`
- Test: `backend/tests/test_tts_queue.py`

- [ ] **Step 1: Write failing queue contract tests**

```python
async def test_queue_reclaims_and_acknowledges(redis_server):
    queue = RedisTtsQueue(redis_server, "tts-jobs", "tts-workers", "worker-1")
    await queue.start()
    await queue.enqueue("tts_1")
    delivery = await queue.next(timeout_ms=50)
    assert delivery.job_id == "tts_1"
    await queue.ack(delivery.message_id)
    assert await queue.depth() == 0


async def test_unacknowledged_message_is_reclaimed(redis_server):
    first = RedisTtsQueue(redis_server, "tts-jobs", "tts-workers", "worker-1")
    second = RedisTtsQueue(redis_server, "tts-jobs", "tts-workers", "worker-2")
    await first.start()
    await first.enqueue("tts_2")
    await first.next(timeout_ms=50)
    delivery = await second.reclaim(min_idle_ms=0)
    assert delivery.job_id == "tts_2"
```

- [ ] **Step 2: Add dependency and verify tests fail**

Add `redis>=5.2,<6` to runtime dependencies and `fakeredis>=2.25,<3` to test dependencies in `backend/pyproject.toml`, install editable dependencies, then run:

`python -m pytest tests/test_tts_queue.py -q`

Expected: FAIL because `RedisTtsQueue` does not exist.

- [ ] **Step 3: Implement queue boundary**

```python
from dataclasses import dataclass
from redis.asyncio import Redis
from redis.exceptions import ResponseError


@dataclass(frozen=True)
class TtsDelivery:
    message_id: str
    job_id: str


class RedisTtsQueue:
    def __init__(self, redis: Redis, stream: str, group: str, consumer: str) -> None:
        self.redis, self.stream, self.group, self.consumer = redis, stream, group, consumer

    async def start(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, job_id: str) -> str:
        return await self.redis.xadd(self.stream, {"job_id": job_id})

    async def next(self, timeout_ms: int = 1000) -> TtsDelivery | None:
        rows = await self.redis.xreadgroup(
            self.group, self.consumer, {self.stream: ">"}, count=1, block=timeout_ms,
        )
        if not rows:
            return None
        message_id, fields = rows[0][1][0]
        return TtsDelivery(message_id.decode(), fields[b"job_id"].decode())

    async def ack(self, message_id: str) -> None:
        await self.redis.xack(self.stream, self.group, message_id)
        await self.redis.xdel(self.stream, message_id)

    async def depth(self) -> int:
        return int(await self.redis.xlen(self.stream))
```

Implement `reclaim()` with `XAUTOCLAIM`. Replace the in-memory `asyncio.Queue` in `TtsManager` with this interface. A synthesis job is acknowledged only after terminal `completed` or non-retryable `failed` state.

- [ ] **Step 4: Run queue and manager tests**

Run: `python -m pytest tests/test_tts_queue.py tests/test_tts_manager.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/tts/queue.py backend/app/tts/manager.py backend/app/core/config.py backend/pyproject.toml backend/tests/test_tts_queue.py backend/tests/test_tts_manager.py
git commit -m "feat: persist TTS dispatch queue in Redis"
```

## Task 4: Retry Worker Outages Without Losing Jobs

**Files:**
- Modify: `backend/app/tts/models.py`
- Modify: `backend/app/tts/repository.py`
- Modify: `backend/app/tts/manager.py`
- Test: `backend/tests/test_tts_repository.py`
- Test: `backend/tests/test_tts_manager.py`

- [ ] **Step 1: Write failing migration and retry tests**

```python
async def test_transient_worker_failure_requeues_job(manager, provider, repository):
    provider.fail_once = TtsProviderError("worker_unavailable", "暂不可用")
    job = await manager.create_job("preset:zh_female", "您好")
    await manager.wait_for_attempt(job.job_id)
    record = await repository.require_job(job.job_id)
    assert record.status == TtsJobStatus.queued
    assert record.attempt_count == 1
    assert record.next_attempt_at is not None


async def test_repository_migrates_retry_columns(tmp_path):
    repository = TtsRepository(tmp_path / "tts.sqlite3")
    await repository.init()
    columns = await repository.table_columns("tts_jobs")
    assert {"attempt_count", "next_attempt_at"}.issubset(columns)
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/test_tts_repository.py tests/test_tts_manager.py -q`

Expected: FAIL because retry fields and behavior do not exist.

- [ ] **Step 3: Implement retry persistence and policy**

Add `attempt_count: int = 0` and `next_attempt_at: datetime | None = None` to `TtsJob`. Migrate SQLite with `ALTER TABLE` guarded by `PRAGMA table_info`. Add repository method:

```python
async def schedule_retry(self, job_id: str, attempt: int, when: datetime) -> None:
    await self._update(
        job_id,
        status=TtsJobStatus.queued,
        attempt_count=attempt,
        next_attempt_at=when,
        error_code="worker_unavailable",
        error_message="语音合成服务恢复后将自动重试",
    )
```

Use delays `[5, 15, 30, 60, 120]` seconds. `worker_unavailable` and `worker_not_ready` are retryable; invalid input, missing preset, expired voice, and model output validation are terminal. Do not increment attempts while health is `starting` or `unavailable`; wait before consuming new queue items.

- [ ] **Step 4: Run TTS backend tests**

Run: `python -m pytest tests/test_tts_repository.py tests/test_tts_manager.py tests/test_tts_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/tts/models.py backend/app/tts/repository.py backend/app/tts/manager.py backend/tests/test_tts_repository.py backend/tests/test_tts_manager.py
git commit -m "feat: retry TTS jobs after worker recovery"
```

## Task 5: Expose Health API and Guard Submission

**Files:**
- Modify: `backend/app/api/tts.py`
- Test: `backend/tests/test_tts_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_tts_health_returns_cached_state(client, manager):
    manager.health_cache.mark_unavailable("worker_not_ready", "模型正在启动")
    response = client.get("/api/tts/health")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"


def test_unavailable_worker_rejects_new_job_without_losing_existing_queue(client, manager):
    manager.health_cache.mark_unavailable("worker_unavailable", "服务暂不可用")
    response = client.post("/api/tts/jobs", json={"voice_id": "preset:zh_female", "text": "您好"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "worker_unavailable"
```

- [ ] **Step 2: Run test and verify failure**

Run: `python -m pytest tests/test_tts_api.py -q`

Expected: FAIL because the health route and readiness guard do not exist.

- [ ] **Step 3: Implement health route and structured 503**

```python
@router.get("/health", response_model=TtsHealthResponse)
async def tts_health(request: Request) -> TtsHealthResponse:
    return _manager(request).health_cache.snapshot()
```

Before creating a job, read the cache. Accept `ready` and `busy`; reject `starting` and `unavailable` with `HTTPException(503, detail={"code": ..., "message": ...})`.

- [ ] **Step 4: Run TTS API tests**

Run: `python -m pytest tests/test_tts_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/api/tts.py backend/tests/test_tts_api.py
git commit -m "feat: expose TTS readiness API"
```

## Task 6: Build Reproducible GPU Worker Container

**Files:**
- Create: `backend/tts_worker/requirements.lock.txt`
- Create: `backend/tts_worker/Dockerfile`
- Modify: `backend/tts_worker/server.py`
- Create: `backend/tests/test_tts_worker_container.py`

- [ ] **Step 1: Write static container contract tests**

```python
def test_worker_image_is_pinned_and_does_not_download_models():
    dockerfile = Path("tts_worker/Dockerfile").read_text(encoding="utf-8")
    assert "nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04" in dockerfile
    assert "python3.10" in dockerfile
    assert "COPY tts_worker/requirements.lock.txt" in dockerfile
    assert "snapshot_download" not in dockerfile
    assert "USER app" in dockerfile


def test_worker_has_liveness_and_readiness_routes():
    source = Path("tts_worker/server.py").read_text(encoding="utf-8")
    assert '"/health/live"' in source
    assert '"/health/ready"' in source
```

- [ ] **Step 2: Run static tests and verify failure**

Run: `python -m pytest tests/test_tts_worker_container.py -q`

Expected: FAIL because the Dockerfile and routes do not exist.

- [ ] **Step 3: Add pinned worker image**

```dockerfile
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends python3.10 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/cosyvoice
COPY tts_worker/requirements.lock.txt /tmp/requirements.lock.txt
RUN python3.10 -m pip install --no-cache-dir -r /tmp/requirements.lock.txt
COPY tts_worker /srv/cosyvoice/tts_worker
RUN useradd --system --uid 10001 app && chown -R app:app /srv/cosyvoice
USER app
CMD ["python3.10", "-m", "uvicorn", "tts_worker.server:app", "--host", "0.0.0.0", "--port", "18081"]
```

Pin CosyVoice source to commit `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc` in `requirements.lock.txt`; do not include model downloads. Require model directories `/models/Fun-CosyVoice3-0.5B` and `/models/CosyVoice-300M-SFT`, plus the release-owned reference fixture `/models/smoke/zero-shot-reference.wav` and its checked prompt text `/models/smoke/zero-shot-reference.txt`. In `server.py`, move model construction to FastAPI lifespan, run one short preset and one zero-shot smoke synthesis into a temporary directory, reject readiness until both produce valid WAV files, and keep `/health/live` independent of model readiness.

- [ ] **Step 4: Build image and run static tests**

Run:

```powershell
cd backend
python -m pytest tests/test_tts_worker_container.py -q
docker build -f tts_worker/Dockerfile -t call-asr-cosyvoice:test .
```

Expected: tests PASS and Docker build exits 0 without downloading model weights.

- [ ] **Step 5: Commit**

```powershell
git add backend/tts_worker backend/tests/test_tts_worker_container.py
git commit -m "build: containerize CosyVoice worker"
```

## Task 7: Add Docker Compose and Offline Model Mounts

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/.env.example`
- Modify: `.gitignore`
- Test: `backend/tests/test_deploy_compose.py`

- [ ] **Step 1: Write failing Compose contract test**

```python
def test_compose_assigns_gpu_and_read_only_models():
    compose = yaml.safe_load(Path("../deploy/docker-compose.yml").read_text())
    worker = compose["services"]["cosyvoice-worker"]
    assert worker["environment"]["CUDA_VISIBLE_DEVICES"] == "1"
    assert any(volume.endswith(":/models:ro") for volume in worker["volumes"])
    assert worker["restart"] == "unless-stopped"
    assert "healthcheck" in worker
```

- [ ] **Step 2: Run and verify failure**

Run: `cd backend; python -m pytest tests/test_deploy_compose.py -q`

Expected: FAIL because Compose does not exist.

- [ ] **Step 3: Add deployment services**

Create Compose services for Redis 7, `cosyvoice-worker`, and the current backend. Configure `CALL_ASR_COSYVOICE_WORKER_URL=http://cosyvoice-worker:18081`, `CALL_ASR_REDIS_URL=redis://redis:6379/0`, NVIDIA device reservation for GPU 1, read-only `${MODEL_ROOT}:/models:ro`, writable `${DATA_ROOT}:/data`, service tokens via environment, health checks, `unless-stopped`, and bounded JSON logs. Do not put token values in `.env.example`.

- [ ] **Step 4: Validate Compose**

Run:

```powershell
cd deploy
Copy-Item .env.example .env
docker compose config
cd ../backend
python -m pytest tests/test_deploy_compose.py -q
```

Expected: Compose config and tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add deploy .gitignore backend/tests/test_deploy_compose.py
git commit -m "ops: add GPU TTS deployment stack"
```

## Task 8: Render Health and Queue State in Vue

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/composables/useTts.ts`
- Modify: `frontend/src/components/TtsPanel.vue`
- Modify: `frontend/src/components/TtsPanel.spec.ts`

- [ ] **Step 1: Write failing component tests**

```typescript
it.each([
  ["starting", "语音合成模型正在启动"],
  ["unavailable", "语音合成服务暂不可用"]
])("disables submit when worker is %s", async (status, message) => {
  api.getTtsHealth.mockResolvedValue({ status, message, queue_depth: 0, checked_at: new Date().toISOString() });
  const wrapper = mount(TtsPanel, { props: { initialText: "您好" } });
  await flushPromises();
  expect(wrapper.text()).toContain(message);
  expect(wrapper.get("button.ttsSubmit").attributes("disabled")).toBeDefined();
});


it("shows queue depth while worker is busy", async () => {
  api.getTtsHealth.mockResolvedValue({ status: "busy", message: "任务较多，已进入队列", queue_depth: 4, checked_at: new Date().toISOString() });
  const wrapper = mount(TtsPanel);
  await flushPromises();
  expect(wrapper.text()).toContain("前方 4 个任务");
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend; npm test -- --run src/components/TtsPanel.spec.ts`

Expected: FAIL because health state is not loaded or rendered.

- [ ] **Step 3: Implement client polling and UI state**

Add `TtsHealth` type matching the backend. Add `getTtsHealth()` in `api/client.ts`. In `useTts`, load immediately and poll every five seconds; clear the timer on unmount. Derive `canSubmit = health.status === "ready" || health.status === "busy"`. Render a compact status row with Chinese message and queue count. Disable synthesis for starting/unavailable states without hiding text or selected voice.

- [ ] **Step 4: Run frontend tests and build**

Run:

```powershell
npm test -- --run src/components/TtsPanel.spec.ts src/composables/useTts.spec.ts
npm run build
```

Expected: PASS and production build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/composables/useTts.ts frontend/src/components/TtsPanel.vue frontend/src/components/TtsPanel.spec.ts
git commit -m "feat: show CosyVoice readiness before synthesis"
```

## Task 9: End-to-End Verification and Operations Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/API.md`

- [ ] **Step 1: Run complete automated checks**

Run:

```powershell
cd backend
python -m pytest -q
cd ../frontend
npm test -- --run
npm run build
```

Expected: all tests PASS and build succeeds.

- [ ] **Step 2: Run container smoke test**

With release artifacts for `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`, `iic/CosyVoice-300M-SFT`, and the synthetic smoke reference mounted, run `docker compose up -d redis cosyvoice-worker backend`, wait for `/health/ready`, synthesize one preset and one authorized reference voice, verify each WAV is larger than 44 bytes, playable, downloadable, and contains finite samples.

- [ ] **Step 3: Verify outage recovery**

Stop `cosyvoice-worker`, confirm the UI becomes unavailable and rejects new submissions. Start it, confirm readiness returns automatically. During a running synthesis, kill the worker and verify the job requeues, increments attempts once, and completes after recovery without duplicate output.

- [ ] **Step 4: Document exact operations**

Document offline model directory layout, required NVIDIA driver/Container Toolkit, environment variables, startup order, readiness endpoints, Redis recovery, retry schedule, logs, model upgrade procedure, and rollback to the previous image digest.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/DEPLOYMENT.md docs/API.md
git commit -m "docs: document resilient CosyVoice operations"
```

## Completion Criteria

- The browser knows worker state before submission and never shows only a late generic connection failure.
- Worker models are mounted offline, loaded and smoke-tested before readiness.
- GPU 1 is explicitly assigned; system proxy variables cannot redirect service traffic.
- Redis retains jobs across backend or worker restart and reclaims unacknowledged delivery.
- Transient outages requeue with bounded backoff; permanent validation errors remain terminal.
- Preset and custom voice synthesis, Range playback, download, retention, and consent still pass.
- Backend tests, frontend tests, production build, Compose validation, real-model smoke, and outage recovery pass.
