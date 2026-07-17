# Transcript-First Async Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make uploaded and URL-based calls expose the transcript immediately after ASR, while emotion, risk, quality, and DeepSeek summary run and fail independently.

**Architecture:** Split the current `AnalysisPipeline.run()` into a stable transcription result and isolated analyzers. Persist the base transcript once, persist analyzer outputs as separate artifacts, and assemble the latest partial result on reads so concurrent modules never overwrite each other. The job remains `running` while background modules execute, but the result endpoint opens as soon as `transcript_status=completed`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, aiosqlite, asyncio executors, Vue 3 Composition API, TypeScript, Vitest, pytest

---

## File Map

### Backend

- Modify `backend/app/jobs/models.py`: add independent module status and error models.
- Modify `backend/app/jobs/repository.py`: migrate job status columns and persist per-module errors.
- Modify `backend/app/core/models.py`: add serializable per-segment emotion and risk artifact models.
- Modify `backend/app/sessions/repository.py`: save and load independent analyzer artifacts.
- Modify `backend/app/sessions/pipeline.py`: separate transcription, emotion, risk, and quality operations.
- Modify `backend/app/jobs/manager.py`: publish transcript first and orchestrate module tasks.
- Modify `backend/app/api/jobs.py`: allow partial result reads and module-specific retries.
- Modify `backend/app/main.py`: wire the refactored pipeline dependencies.
- Modify `backend/tests/test_job_models.py`, `test_job_manager.py`, `test_analysis_pipeline.py`, `test_jobs_api.py`: cover statuses, ordering, failures, retries, and partial results.

### Frontend

- Modify `frontend/src/types.ts`: represent module statuses and nullable partial artifacts.
- Modify `frontend/src/composables/useAnalysisJob.ts`: fetch results when transcript completes and continue polling modules.
- Create `frontend/src/components/ModuleState.vue`: shared pending/running/failed state and retry control.
- Modify `frontend/src/App.vue`: render transcript as soon as available and pass module states.
- Modify `frontend/src/components/EmotionChart.vue`, `QualityPanel.vue`, `SensitivePanel.vue`, `SummaryPanel.vue`: render through independent states.
- Modify `frontend/src/api/client.ts`: add module retry API.
- Modify `frontend/src/App.spec.ts` and create focused component/composable tests.

## Task 1: Add Independent Module Status Persistence

**Files:**
- Modify: `backend/app/jobs/models.py`
- Modify: `backend/app/jobs/repository.py`
- Test: `backend/tests/test_job_models.py`
- Test: `backend/tests/test_job_repository.py`

- [ ] **Step 1: Write failing model and repository tests**

Add tests that require every new job to start with independent states and verify one module can fail without changing the others:

```python
from app.jobs.models import ModuleStatus


async def test_repository_tracks_module_statuses_independently(repository):
    await repository.create("job_1", "call_1", "upload")
    record = await repository.require("job_1")
    assert record.transcript_status == ModuleStatus.pending
    assert record.emotion_status == ModuleStatus.pending
    assert record.risk_status == ModuleStatus.pending
    assert record.quality_status == ModuleStatus.pending

    await repository.set_module_status(
        "job_1", "emotion", ModuleStatus.failed, "emotion_failed", "情绪分析失败"
    )
    record = await repository.require("job_1")
    assert record.emotion_status == ModuleStatus.failed
    assert record.risk_status == ModuleStatus.pending
    assert (await repository.get_module_errors("job_1"))["emotion"].code == "emotion_failed"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
cd backend
python -m pytest tests/test_job_models.py tests/test_job_repository.py -q
```

Expected: FAIL because `ModuleStatus`, the four new fields, and `set_module_status()` do not exist.

- [ ] **Step 3: Implement the status models and SQLite migration**

Add to `backend/app/jobs/models.py`:

```python
class ModuleStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ModuleError(BaseModel):
    code: str
    message: str


class JobStatusResponse(JobCreateResponse):
    transcript_status: ModuleStatus = ModuleStatus.pending
    emotion_status: ModuleStatus = ModuleStatus.pending
    risk_status: ModuleStatus = ModuleStatus.pending
    quality_status: ModuleStatus = ModuleStatus.pending
    summary_status: ModuleStatus = ModuleStatus.pending
    module_errors: dict[str, ModuleError] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
```

Replace the old `SummaryStatus` enum with `ModuleStatus` throughout backend callers and tests so every module uses one status type. Keep the JSON values unchanged for API compatibility.

In `backend/app/jobs/repository.py`, extend the table and migrate existing databases without dropping data:

```python
MODULE_COLUMNS = {
    "transcript": "transcript_status",
    "emotion": "emotion_status",
    "risk": "risk_status",
    "quality": "quality_status",
    "summary": "summary_status",
}


async def _ensure_job_columns(db: aiosqlite.Connection) -> None:
    rows = await (await db.execute("PRAGMA table_info(jobs)")).fetchall()
    existing = {row[1] for row in rows}
    for column in ("transcript_status", "emotion_status", "risk_status", "quality_status"):
        if column not in existing:
            await db.execute(
                f"ALTER TABLE jobs ADD COLUMN {column} TEXT NOT NULL DEFAULT 'pending'"
            )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS job_module_errors (
            job_id TEXT NOT NULL,
            module TEXT NOT NULL,
            code TEXT NOT NULL,
            message TEXT NOT NULL,
            PRIMARY KEY (job_id, module)
        )
        """
    )
```

Implement `set_module_status()` with the module-to-column whitelist above. Delete an old error when a module enters `running` or `completed`, and upsert an error only for `failed`.

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
python -m pytest tests/test_job_models.py tests/test_job_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/jobs/models.py backend/app/jobs/repository.py backend/tests/test_job_models.py backend/tests/test_job_repository.py
git commit -m "feat: track analysis module statuses"
```

## Task 2: Store Analyzer Outputs Without Rewriting Base Segments

**Files:**
- Modify: `backend/app/core/models.py`
- Modify: `backend/app/sessions/repository.py`
- Test: `backend/tests/test_session_repository.py`

- [ ] **Step 1: Write failing artifact merge tests**

```python
async def test_analysis_artifacts_merge_without_overwriting_transcript(repository, segment):
    await repository.save_segments("call_1", [segment])
    await repository.save_emotions(
        "call_1", {segment.id: EmotionResult(label="angry", confidence=0.8, score=-0.8)}
    )
    await repository.save_risks(
        "call_1",
        {segment.id: SegmentRiskArtifact(sensitive_hits=[], compliance_hits=[])},
    )

    merged = await repository.list_enriched_segments("call_1")
    assert merged[0].text == segment.text
    assert merged[0].emotion.label == "angry"
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
python -m pytest tests/test_session_repository.py -q
```

Expected: FAIL because artifact methods do not exist.

- [ ] **Step 3: Add artifact models and repository methods**

Add to `backend/app/core/models.py`:

```python
class SegmentRiskArtifact(BaseModel):
    sensitive_hits: list[SensitiveHit] = Field(default_factory=list)
    compliance_hits: list[ComplianceHit] = Field(default_factory=list)
```

Add JSON artifact methods to `SessionRepository`:

```python
async def save_emotions(self, session_id: str, values: dict[str, EmotionResult]) -> None:
    payload = {key: value.model_dump(mode="json") for key, value in values.items()}
    await self._save_artifact(session_id, "emotions", json.dumps(payload, ensure_ascii=False))


async def save_risks(self, session_id: str, values: dict[str, SegmentRiskArtifact]) -> None:
    payload = {key: value.model_dump(mode="json") for key, value in values.items()}
    await self._save_artifact(session_id, "risks", json.dumps(payload, ensure_ascii=False))


async def list_enriched_segments(self, session_id: str) -> list[Segment]:
    segments = await self.list_segments(session_id)
    emotions = await self.get_emotions(session_id)
    risks = await self.get_risks(session_id)
    for segment in segments:
        if segment.id in emotions:
            segment.emotion = emotions[segment.id]
        if segment.id in risks:
            segment.sensitive_hits = risks[segment.id].sensitive_hits
            segment.compliance_hits = risks[segment.id].compliance_hits
    return segments
```

Use `json.dumps(payload, ensure_ascii=False)` and Pydantic validation on reads. A missing artifact returns an empty dictionary.

- [ ] **Step 4: Run the repository tests**

```powershell
python -m pytest tests/test_session_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/core/models.py backend/app/sessions/repository.py backend/tests/test_session_repository.py
git commit -m "feat: persist independent analysis artifacts"
```

## Task 3: Split Transcription From Post-Analysis

**Files:**
- Modify: `backend/app/sessions/pipeline.py`
- Test: `backend/tests/test_analysis_pipeline.py`

- [ ] **Step 1: Write failing pipeline phase tests**

Require transcription to return before emotion or risk providers are called:

```python
def test_transcribe_does_not_run_post_analysis(pipeline, emotion, sensitive_store, stereo_audio):
    result = pipeline.transcribe(stereo_audio, "call_1", lambda *_: None)
    assert result.segments
    emotion.analyze_many.assert_not_called()
    sensitive_store.scan.assert_not_called()


def test_analyze_emotion_returns_artifact_map(pipeline, transcription):
    result = pipeline.analyze_emotion(transcription)
    assert set(result) == {segment.id for segment in transcription.segments}
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_analysis_pipeline.py -q
```

Expected: FAIL because only `run()` exists.

- [ ] **Step 3: Introduce phase-specific results and methods**

Refactor `backend/app/sessions/pipeline.py` around this immutable transcription result:

```python
@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[Segment]
    channel_audio: dict[Speaker, bytes]
    silence_ratio: float
    noise_level: str


def transcribe(self, audio_bytes: bytes, session_id: str, progress: ProgressCallback) -> TranscriptionResult:
    progress(JobStage.preparing_audio, 5)
    channels = self.audio.split_required_stereo(audio_bytes)
    progress(JobStage.transcribing_sales, 15)
    sales = self.asr.transcribe(channels.right, session_id, Speaker.sales)
    progress(JobStage.transcribing_customer, 40)
    customer = self.asr.transcribe(channels.left, session_id, Speaker.customer)
    segments = merge_channel_segments(sales, customer)
    if not segments:
        raise AnalysisPipelineError("asr_failed", "录音中未识别到有效语音")
    processed = self.audio.process(audio_bytes)
    return TranscriptionResult(
        segments=segments,
        channel_audio={Speaker.sales: channels.right, Speaker.customer: channels.left},
        silence_ratio=processed.silence_ratio,
        noise_level=processed.noise_level,
    )
```

Add `analyze_emotion()`, `scan_risks()`, and `score_quality()` methods. `score_quality()` accepts already enriched segments so it can run after emotion and risk tasks settle. Remove `LocalAnalysisResult` after all callers migrate.

- [ ] **Step 4: Run pipeline tests**

```powershell
python -m pytest tests/test_analysis_pipeline.py -q
```

Expected: PASS, including stereo role order and native timestamps.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/sessions/pipeline.py backend/tests/test_analysis_pipeline.py
git commit -m "refactor: split transcript and analysis phases"
```

## Task 4: Publish Transcript Before Background Modules

**Files:**
- Modify: `backend/app/jobs/manager.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_job_manager.py`

- [ ] **Step 1: Write the blocking-analyzer regression test**

```python
async def test_transcript_is_readable_while_analyzers_are_blocked(manager, jobs, sessions):
    entered = threading.Event()
    release = threading.Event()

    def blocking_emotion(transcription):
        entered.set()
        assert release.wait(timeout=5)
        return {
            segment.id: EmotionResult(label="neutral", confidence=0.9, score=0)
            for segment in transcription.segments
        }

    manager.pipeline.analyze_emotion = blocking_emotion
    created = await manager.create_upload(STEREO_WAV, "audio/wav")

    assert await asyncio.to_thread(entered.wait, 2)
    record = await jobs.require(created.job_id)
    assert record.transcript_status == ModuleStatus.completed
    result = await manager.get_result(created.job_id)
    assert result.segments
    assert result.emotion_status == ModuleStatus.running
    assert result.summary_status == ModuleStatus.running

    release.set()
    await manager.wait(created.job_id)
```

Add separate tests where emotion, risk, and summary fail. Each test must assert that `get_result()` still returns the transcript and unaffected modules continue.

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_job_manager.py -q
```

Expected: FAIL because `get_result()` still requires overall completion.

- [ ] **Step 3: Refactor JobManager orchestration**

Use this lifecycle in `_analyze()`:

```python
transcription = await loop.run_in_executor(
    self.executor,
    self.pipeline.transcribe,
    source_path.read_bytes(),
    record.session_id,
    progress,
)
await self.sessions.save_segments(record.session_id, transcription.segments)
await self.jobs.set_module_status(job_id, "transcript", ModuleStatus.completed)
await self.jobs.update_progress(job_id, JobStage.merging_segments, 65)

module_tasks = [
    self._run_emotion(job_id, record.session_id, transcription),
    self._run_risk(job_id, record.session_id, transcription.segments),
    self._run_summary(job_id, record.session_id, transcription.segments),
]
emotion_result, risk_result, _ = await asyncio.gather(*module_tasks, return_exceptions=True)
await self._run_quality(job_id, record.session_id, transcription)
await self.jobs.complete(job_id)
```

Every `_run_*` method sets only its own module state, catches its public error, and persists only its own artifact. `get_result()` checks `transcript_status`, not overall `status`, and assembles enriched segments from repository artifacts.

`_run_quality()` must reload `list_enriched_segments(session_id)` after emotion and risk tasks reach a terminal state. If either artifact is unavailable because its module failed, use the base segment defaults, add a quality suggestion that the corresponding input was unavailable, and still complete the quality module. Never score from the stale `transcription.segments` objects captured before analyzer artifacts were saved.

Keep the executor bounded. DeepSeek remains native async I/O. Local emotion work uses `run_in_executor`; risk scanning runs in the executor only if it would block the event loop for a measurable duration.

- [ ] **Step 4: Run manager tests**

```powershell
python -m pytest tests/test_job_manager.py -q
```

Expected: PASS. The blocking test must observe transcript content before releasing analyzers.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/jobs/manager.py backend/app/main.py backend/tests/test_job_manager.py
git commit -m "feat: publish transcript before async analysis"
```

## Task 5: Add Partial Result and Module Retry APIs

**Files:**
- Modify: `backend/app/jobs/models.py`
- Modify: `backend/app/api/jobs.py`
- Modify: `backend/app/jobs/manager.py`
- Test: `backend/tests/test_jobs_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_result_opens_when_transcript_is_complete(client, manager):
    manager.status.transcript_status = ModuleStatus.completed
    manager.status.status = JobStatus.running
    response = client.get("/api/jobs/job_1/result")
    assert response.status_code == 200
    assert response.json()["segments"]
    assert response.json()["emotion_status"] == "running"


def test_retry_only_requested_module(client, manager):
    response = client.post("/api/jobs/job_1/retry/emotion")
    assert response.status_code == 202
    assert manager.retried == ("job_1", "emotion")
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_jobs_api.py -q
```

Expected: FAIL because partial results and generic retry do not exist.

- [ ] **Step 3: Implement response fields and retry route**

Make `quality` and `summary` optional in `JobAnalysisResponse` and include all five statuses plus `module_errors`.

Add a constrained route:

```python
RetryModule = Literal["emotion", "risk", "quality", "summary"]


@router.post("/{job_id}/retry/{module}", response_model=JobStatusResponse, status_code=202)
async def retry_module(request: Request, job_id: str, module: RetryModule) -> JobStatusResponse:
    try:
        return await _manager(request).retry_module(job_id, module)
    except JobNotReadyError as exc:
        raise HTTPException(status_code=409, detail="当前模块状态不能重试") from exc
```

Preserve `POST /retry-summary` as a deprecated compatibility alias that calls `retry_module(job_id, "summary")`.

- [ ] **Step 4: Run API tests**

```powershell
python -m pytest tests/test_jobs_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/jobs/models.py backend/app/api/jobs.py backend/app/jobs/manager.py backend/tests/test_jobs_api.py
git commit -m "feat: expose partial analysis results"
```

## Task 6: Fetch and Render Transcript While Job Is Running

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/composables/useAnalysisJob.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/composables/useAnalysisJob.spec.ts`

- [ ] **Step 1: Write failing composable tests**

Use fake timers and mocked API calls:

```typescript
it("loads transcript before the overall job completes", async () => {
  vi.mocked(getJob).mockResolvedValue({
    job_id: "job_1",
    session_id: "call_1",
    status: "running",
    stage: "analyzing_emotion",
    progress: 72,
    transcript_status: "completed",
    emotion_status: "running",
    risk_status: "running",
    quality_status: "pending",
    summary_status: "running",
    module_errors: {}
  });
  vi.mocked(getJobResult).mockResolvedValue(partialResult);

  const state = useAnalysisJob();
  await state.submitUrl("https://example.com/call.wav");
  expect(state.result.value?.segments).toHaveLength(2);
  expect(state.isWorking.value).toBe(true);
});
```

- [ ] **Step 2: Run and verify failure**

```powershell
cd frontend
npm test -- --run src/composables/useAnalysisJob.spec.ts
```

Expected: FAIL because results are fetched only when overall status is `completed`.

- [ ] **Step 3: Update types and polling logic**

Add:

```typescript
export type ModuleStatus = "pending" | "running" | "completed" | "failed";

export interface ModuleError {
  code: string;
  message: string;
}
```

Add status fields to both job and result types. Make `quality` and `summary` optional.

In `poll()`, fetch whenever the transcript is complete and keep polling until overall status is terminal:

```typescript
if (status.transcript_status === "completed") {
  result.value = await getJobResult(jobId);
}
if (status.status === "running" || status.status === "queued") {
  pollTimer = setTimeout(() => void poll(jobId, current), 1000);
  return;
}
```

Add `retryModule(jobId, module)` to the API client and expose it from the composable.

- [ ] **Step 4: Run composable tests**

```powershell
npm test -- --run src/composables/useAnalysisJob.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/composables/useAnalysisJob.ts frontend/src/composables/useAnalysisJob.spec.ts
git commit -m "feat: load transcript while analysis continues"
```

## Task 7: Add Independent Module UI States

**Files:**
- Create: `frontend/src/components/ModuleState.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/EmotionChart.vue`
- Modify: `frontend/src/components/QualityPanel.vue`
- Modify: `frontend/src/components/SensitivePanel.vue`
- Modify: `frontend/src/components/SummaryPanel.vue`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/App.spec.ts`
- Test: `frontend/src/components/ModuleState.spec.ts`

- [ ] **Step 1: Write failing UI tests**

```typescript
it("keeps transcript visible while each analysis panel has its own state", async () => {
  mockAnalysisJob({ result: partialResult });
  const wrapper = mount(App);
  expect(wrapper.find("[aria-label='通话内容']").text()).toContain("您好");
  expect(wrapper.find("[data-module='emotion']").text()).toContain("情绪分析中");
  expect(wrapper.find("[data-module='risk']").text()).toContain("风险分析中");
});


it("retries only the failed module", async () => {
  const wrapper = mount(ModuleState, {
    props: { module: "emotion", status: "failed", error: "情绪分析失败" }
  });
  await wrapper.get("button").trigger("click");
  expect(wrapper.emitted("retry")).toEqual([["emotion"]]);
});
```

- [ ] **Step 2: Run and verify failure**

```powershell
npm test -- --run src/App.spec.ts src/components/ModuleState.spec.ts
```

Expected: FAIL because the workspace is still gated by a complete result and no shared module state exists.

- [ ] **Step 3: Implement module-state rendering**

`ModuleState.vue` owns only pending/running/failed presentation:

```vue
<template>
  <div :data-module="module" class="moduleState" role="status">
    <LoaderCircle v-if="status === 'running'" class="spin" :size="18" />
    <Clock3 v-else-if="status === 'pending'" :size="18" />
    <CircleAlert v-else :size="18" />
    <span>{{ message }}</span>
    <button v-if="status === 'failed'" type="button" @click="$emit('retry', module)">
      <RotateCw :size="16" />重新分析
    </button>
  </div>
</template>
```

In `App.vue`, render the workspace as soon as `result` exists. Always place `TranscriptPanel` first in the primary column. Wrap each optional artifact with its own state. Do not hide or replace transcript content when a module fails.

- [ ] **Step 4: Run UI tests and build**

```powershell
npm test -- --run src/App.spec.ts src/components/ModuleState.spec.ts
npm run build
```

Expected: tests PASS and Vite build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/App.vue frontend/src/components/ModuleState.vue frontend/src/components/ModuleState.spec.ts frontend/src/components/EmotionChart.vue frontend/src/components/QualityPanel.vue frontend/src/components/SensitivePanel.vue frontend/src/components/SummaryPanel.vue frontend/src/styles.css frontend/src/App.spec.ts
git commit -m "feat: show independent analysis panel states"
```

## Task 8: Full Regression, Migration Check, and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Test migration from an existing database**

Create a temporary SQLite database using the pre-change `jobs` schema, run `JobRepository.init()`, and assert the four new status columns exist with `pending` defaults. Add this as `test_init_migrates_existing_jobs_table` in `backend/tests/test_job_repository.py`.

- [ ] **Step 2: Run the complete backend suite**

```powershell
cd backend
python -m pytest -q
```

Expected: all backend tests PASS.

- [ ] **Step 3: Run the complete frontend suite and build**

```powershell
cd ../frontend
npm test -- --run
npm run build
```

Expected: all frontend tests PASS and production build succeeds. The existing chunk-size warning is acceptable; new TypeScript errors are not.

- [ ] **Step 4: Update API and architecture documentation**

Document that `GET /api/jobs/{job_id}/result` becomes available when `transcript_status=completed`, list all module states, and document `POST /api/jobs/{job_id}/retry/{module}` with the four accepted modules.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/API.md docs/ARCHITECTURE.md backend/tests/test_job_repository.py
git commit -m "docs: explain transcript-first analysis"
```

## Completion Criteria

- Transcript content is readable while the overall job is still running.
- Emotion, risk, quality, and summary statuses change independently.
- One module failure cannot remove transcript content or stop unrelated modules.
- Concurrent analyzer writes cannot overwrite base transcript text or each other's artifacts.
- Each failed module has a focused retry path that does not rerun ASR.
- Existing SQLite databases migrate in place.
- Backend tests, frontend tests, and production build pass.
