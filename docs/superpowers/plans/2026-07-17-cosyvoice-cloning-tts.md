# CosyVoice Cloning TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users upload an authorized 3-30 second voice reference, synthesize arbitrary or transcript text with that voice using Fun-CosyVoice 3, and play or download temporary generated audio without disrupting realtime ASR.

**Architecture:** Keep TTS API, validation, storage, and task state in the existing FastAPI application. Run the official CosyVoice runtime as one persistent localhost worker under its required Python 3.10 environment, because the current application uses Python 3.13 and the official dependency set is not compatible with an in-process install. The main app transcribes the reference clip to obtain `prompt_text`, queues synthesis, waits behind active realtime ASR, and calls the worker using local file paths and a private token.

**Tech Stack:** FastAPI, httpx, aiosqlite, Fun-CosyVoice3-0.5B-2512, ModelScope, Python 3.10 worker, PyTorch/torchaudio, Vue 3, TypeScript, Vitest, pytest

---

## Prerequisites

Complete these plans first:

1. `docs/superpowers/plans/2026-07-17-transcript-first-async-analysis.md`
2. `docs/superpowers/plans/2026-07-17-browser-realtime-asr.md`

The TTS queue relies on realtime activity state so it can yield compute resources to live ASR.

## Verified Upstream Baseline

Pin the worker setup to official CosyVoice commit `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc` and model `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`. The official repository currently requires a recursive clone and a Python 3.10 Conda environment. Its zero-shot API requires target text, reference transcript (`prompt_text`), and reference audio (`prompt_speech`). Do not silently upgrade the repository or model during implementation.

## File Map

### Backend application

- Create `backend/app/tts/models.py`: voice and synthesis task API/domain models.
- Create `backend/app/tts/repository.py`: SQLite voice/job persistence.
- Create `backend/app/tts/storage.py`: reference/output files and expiry cleanup.
- Create `backend/app/tts/provider.py`: worker-client protocol and HTTP implementation.
- Create `backend/app/tts/manager.py`: validation, reference ASR, queue, and lifecycle.
- Create `backend/app/api/tts.py`: clone, create, status, audio, and download routes.
- Create `backend/app/core/inference_gate.py`: realtime-priority gate used by realtime and TTS managers.
- Create `backend/app/audio/responses.py`: shared HTTP Range file response helper.
- Modify `backend/app/api/jobs.py`: use the shared audio response helper.
- Modify `backend/app/realtime/manager.py`: enter/leave the inference gate for active calls.
- Modify `backend/app/core/config.py`, `main.py`, `.env.example`, `.gitignore`.
- Add focused pytest files under `backend/tests/`.

### Isolated worker and setup

- Create `backend/tts_worker/server.py`: persistent localhost CosyVoice process.
- Create `backend/scripts/setup_cosyvoice.ps1`: pinned recursive clone, Conda env, dependencies, and model download.
- Create `backend/scripts/start_cosyvoice.ps1`: start the worker with configured paths and private token.

### Frontend

- Create `frontend/src/components/TtsPanel.vue` and tests.
- Create `frontend/src/composables/useTts.ts` and tests.
- Modify `frontend/src/api/client.ts`, `types.ts`, `App.vue`, `TranscriptPanel.vue`, and `styles.css`.

## Task 1: Define TTS Domain Models and SQLite Persistence

**Files:**
- Create: `backend/app/tts/__init__.py`
- Create: `backend/app/tts/models.py`
- Create: `backend/app/tts/repository.py`
- Create: `backend/tests/test_tts_repository.py`

- [ ] **Step 1: Write failing repository lifecycle tests**

```python
async def test_voice_and_job_lifecycle(repository, now):
    voice = await repository.create_voice(
        "voice_1", Path("prompt.wav"), "您好，这是参考声音。", now + timedelta(days=7)
    )
    job = await repository.create_job("tts_1", voice.id, "需要合成的文字。")
    assert job.status == TtsJobStatus.queued

    await repository.set_job_running(job.id)
    await repository.complete_job(job.id, Path("result.wav"))
    completed = await repository.require_job(job.id)
    assert completed.status == TtsJobStatus.completed
    assert completed.output_path == Path("result.wav")


async def test_expired_voice_cannot_create_job(repository, expired_voice):
    with pytest.raises(VoiceExpiredError):
        await repository.create_job("tts_2", expired_voice.id, "文本")
```

- [ ] **Step 2: Run and verify failure**

```powershell
cd backend
python -m pytest tests/test_tts_repository.py -q
```

Expected: FAIL because the TTS package does not exist.

- [ ] **Step 3: Implement models and tables**

Use explicit statuses:

```python
class TtsJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    expired = "expired"


class TtsVoice(BaseModel):
    id: str
    prompt_path: Path
    prompt_text: str
    expires_at: datetime


class TtsJob(BaseModel):
    id: str
    voice_id: str
    text: str
    status: TtsJobStatus
    output_path: Path | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
```

Create `tts_voices` and `tts_jobs` tables with foreign-key-compatible IDs, ISO UTC timestamps, and indexed expiry/status fields. Repository methods must use bound SQL parameters and convert paths only at the boundary.

- [ ] **Step 4: Run repository tests**

```powershell
python -m pytest tests/test_tts_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/tts backend/tests/test_tts_repository.py
git commit -m "feat: persist temporary TTS voices and jobs"
```

## Task 2: Add Temporary Voice and Output Storage

**Files:**
- Create: `backend/app/tts/storage.py`
- Create: `backend/tests/test_tts_storage.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing storage tests**

```python
def test_storage_uses_opaque_directories_and_cleans_expired(tmp_path):
    storage = TtsStorage(tmp_path, retention_days=7, max_reference_bytes=20 * 1024 * 1024)
    prompt = storage.save_reference("voice_opaque", b"RIFF" + b"\x00" * 40, ".wav")
    output = storage.output_path("tts_opaque")
    assert prompt == tmp_path / "voices" / "voice_opaque" / "prompt.wav"
    assert output == tmp_path / "jobs" / "tts_opaque" / "result.wav"
    mark_old(prompt.parent, days=8)
    assert prompt.parent in storage.cleanup_expired()


def test_rejects_reference_over_20_mb(tmp_path):
    storage = TtsStorage(tmp_path, retention_days=7, max_reference_bytes=20)
    with pytest.raises(TtsStorageLimitError):
        storage.save_reference("voice_1", b"x" * 21, ".wav")
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_tts_storage.py -q
```

Expected: FAIL because storage does not exist.

- [ ] **Step 3: Implement scoped storage and cleanup**

Allow only `.wav`, `.mp3`, `.m4a`, and `.aac`. Validate IDs against `^[a-z0-9_]+$`, resolve every path, and assert it remains below the configured TTS root. Write bytes atomically through a sibling `.tmp` file and `Path.replace()`.

Add `backend/data/tts/` to `.gitignore`. Cleanup must remove only directories whose recorded expiry is past, never a computed parent outside the TTS root.

- [ ] **Step 4: Run storage tests**

```powershell
python -m pytest tests/test_tts_storage.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/tts/storage.py backend/tests/test_tts_storage.py .gitignore
git commit -m "feat: store temporary TTS audio safely"
```

## Task 3: Add the Persistent CosyVoice Worker and Client

**Files:**
- Create: `backend/tts_worker/server.py`
- Create: `backend/app/tts/provider.py`
- Create: `backend/tests/test_tts_provider.py`

- [ ] **Step 1: Write failing provider contract tests**

```python
async def test_provider_sends_zero_shot_inputs(httpx_mock, tmp_path):
    httpx_mock.add_response(url="http://127.0.0.1:18081/synthesize", json={"ok": True})
    provider = CosyVoiceWorkerProvider(
        "http://127.0.0.1:18081", "secret", timeout=120
    )
    await provider.synthesize(
        text="您好。",
        prompt_text="这是参考音频。",
        prompt_path=tmp_path / "prompt.wav",
        output_path=tmp_path / "result.wav",
    )
    request = httpx_mock.get_request()
    assert request.headers["X-Worker-Token"] == "secret"


async def test_provider_maps_worker_failure_to_public_error(httpx_mock):
    httpx_mock.add_response(status_code=503, json={"code": "model_unavailable"})
    with pytest.raises(TtsProviderError, match="语音合成模型暂不可用"):
        await provider.synthesize(
            text="您好。",
            prompt_text="这是参考音频。",
            prompt_path=Path("prompt.wav"),
            output_path=Path("result.wav"),
        )
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_tts_provider.py -q
```

Expected: FAIL because provider and worker do not exist.

- [ ] **Step 3: Implement the localhost worker**

The worker loads the official model once:

```python
from cosyvoice.cli.cosyvoice import AutoModel
import torch
import torchaudio

MODEL = AutoModel(model_dir=os.environ["COSYVOICE_MODEL_DIR"])


def synthesize(request: SynthesisRequest) -> None:
    chunks = []
    prompt = f"You are a helpful assistant.<|endofprompt|>{request.prompt_text}"
    for result in MODEL.inference_zero_shot(
        request.text,
        prompt,
        request.prompt_path,
        stream=False,
    ):
        chunks.append(result["tts_speech"])
    if not chunks:
        raise RuntimeError("CosyVoice returned no audio")
    speech = torch.cat(chunks, dim=1)
    torchaudio.save(request.output_path, speech.cpu(), MODEL.sample_rate)
```

Expose only `GET /health` and `POST /synthesize` on `127.0.0.1`. Require `X-Worker-Token`, accept local absolute paths only below configured TTS roots, serialize inference with one lock, and write operational logs to stderr without text or audio paths.

The main provider uses `httpx.AsyncClient`, maps worker errors to stable Chinese public errors, and verifies `result.wav` exists and is non-empty before reporting success.

- [ ] **Step 4: Run provider tests**

```powershell
python -m pytest tests/test_tts_provider.py -q
```

Expected: PASS using the fake HTTP worker; the real model is not loaded in unit tests.

- [ ] **Step 5: Commit**

```powershell
git add backend/tts_worker/server.py backend/app/tts/provider.py backend/tests/test_tts_provider.py
git commit -m "feat: connect persistent CosyVoice worker"
```

## Task 4: Create a Reproducible CosyVoice Setup

**Files:**
- Create: `backend/scripts/setup_cosyvoice.ps1`
- Create: `backend/scripts/start_cosyvoice.ps1`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add a setup script dry-run test**

Create `backend/tests/test_cosyvoice_setup_script.py` that reads the script and asserts it contains the exact upstream commit, recursive submodule initialization, Python 3.10 environment, model ID, and no API secrets.

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_cosyvoice_setup_script.py -q
```

Expected: FAIL because setup scripts do not exist.

- [ ] **Step 3: Implement pinned PowerShell setup and startup**

`setup_cosyvoice.ps1` must perform explicit, idempotent steps:

```powershell
$Commit = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
$Model = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git $CosyVoiceRoot
git -C $CosyVoiceRoot fetch origin $Commit
git -C $CosyVoiceRoot checkout $Commit
git -C $CosyVoiceRoot submodule update --init --recursive
conda create -n $EnvName -y python=3.10
conda run -n $EnvName python -m pip install -r "$CosyVoiceRoot\requirements.txt"
conda run -n $EnvName python -c "from modelscope import snapshot_download; snapshot_download('$Model', local_dir=r'$ModelDir')"
```

When directories already exist, verify rather than reclone. `start_cosyvoice.ps1` reads `COSYVOICE_WORKER_TOKEN` from the environment and starts the worker hidden on `127.0.0.1`.

Add settings for worker URL, token, timeout, TTS data directory, retention days, reference limits, and model directory. Do not put a real worker token in `.env.example`.

- [ ] **Step 4: Run script test and configuration tests**

```powershell
python -m pytest tests/test_cosyvoice_setup_script.py tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/scripts/setup_cosyvoice.ps1 backend/scripts/start_cosyvoice.ps1 backend/app/core/config.py backend/tests/test_cosyvoice_setup_script.py .env.example README.md
git commit -m "docs: add pinned CosyVoice setup"
```

## Task 5: Validate and Register an Authorized Reference Voice

**Files:**
- Create: `backend/app/tts/manager.py`
- Modify: `backend/app/audio/preprocessor.py`
- Create: `backend/tests/test_tts_manager.py`

- [ ] **Step 1: Write failing reference validation tests**

```python
async def test_create_voice_normalizes_and_transcribes_reference(manager):
    voice = await manager.create_voice(
        audio=REFERENCE_WAV_8_SECONDS,
        filename="reference.wav",
        consent=True,
    )
    assert voice.prompt_text == "您好，这是参考声音。"
    assert voice.prompt_path.name == "prompt.wav"
    assert voice.expires_at > datetime.now(UTC)


@pytest.mark.parametrize("duration", [2.9, 30.1])
async def test_rejects_reference_outside_duration(manager, duration):
    with pytest.raises(TtsValidationError):
        await manager.create_voice(make_wav(duration), "voice.wav", consent=True)


async def test_rejects_missing_consent_or_no_speech(manager):
    with pytest.raises(TtsValidationError, match="授权"):
        await manager.create_voice(REFERENCE_WAV, "voice.wav", consent=False)
    manager.asr.transcribe.return_value = []
    with pytest.raises(TtsValidationError, match="有效人声"):
        await manager.create_voice(SILENCE_WAV, "voice.wav", consent=True)
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_tts_manager.py -q
```

Expected: FAIL because `TtsManager` does not exist.

- [ ] **Step 3: Implement validation and prompt transcription**

`create_voice()` must:

1. Reject missing consent before saving bytes.
2. Reject files over 20 MB and extensions outside WAV/MP3/M4A/AAC.
3. Decode and normalize to mono 16kHz WAV.
4. Read exact duration and require `3.0 <= seconds <= 30.0`.
5. Run the existing ASR provider with `Speaker.unknown`.
6. Join non-empty segments into `prompt_text` and reject silence.
7. Save normalized `prompt.wav`, create an opaque `voice_id`, and expire it in 7 days.

Use the existing model registry instead of constructing a second offline ASR model.

- [ ] **Step 4: Run manager reference tests**

```powershell
python -m pytest tests/test_tts_manager.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/tts/manager.py backend/app/audio/preprocessor.py backend/tests/test_tts_manager.py
git commit -m "feat: register authorized reference voices"
```

## Task 6: Queue Synthesis Behind Active Realtime ASR

**Files:**
- Create: `backend/app/core/inference_gate.py`
- Modify: `backend/app/realtime/manager.py`
- Modify: `backend/app/tts/manager.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_inference_gate.py`
- Modify: `backend/tests/test_tts_manager.py`

- [ ] **Step 1: Write failing priority tests**

```python
async def test_tts_waits_until_realtime_session_ends(gate, tts_manager):
    await gate.realtime_started()
    job = await tts_manager.create_job("voice_1", "您好")
    await asyncio.sleep(0)
    assert (await tts_manager.repository.require_job(job.id)).status == TtsJobStatus.queued
    assert tts_manager.provider.calls == []

    await gate.realtime_ended()
    await tts_manager.wait(job.id)
    assert tts_manager.provider.calls


async def test_gate_never_has_negative_active_count(gate):
    with pytest.raises(RuntimeError):
        await gate.realtime_ended()
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_inference_gate.py tests/test_tts_manager.py -q
```

Expected: FAIL because no resource gate exists.

- [ ] **Step 3: Implement the gate and single-worker TTS queue**

```python
class InferenceGate:
    def __init__(self) -> None:
        self._active_realtime = 0
        self._condition = asyncio.Condition()

    async def wait_for_background_slot(self) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._active_realtime == 0)
```

Provide balanced `realtime_started()` and `realtime_ended()` methods. Wire them to realtime session start/final close using `try/finally`.

`TtsManager` owns one `asyncio.Queue[str]` and one worker task. It validates `1 <= len(text.strip()) <= 2000`, sets the task to `queued`, waits on the gate, sets `running`, calls the provider, verifies output, then completes or fails only that job.

- [ ] **Step 4: Run priority and manager tests**

```powershell
python -m pytest tests/test_inference_gate.py tests/test_tts_manager.py tests/test_realtime_manager.py -q
```

Expected: PASS. A live realtime session must keep TTS queued.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/core/inference_gate.py backend/app/realtime/manager.py backend/app/tts/manager.py backend/app/main.py backend/tests/test_inference_gate.py backend/tests/test_tts_manager.py backend/tests/test_realtime_manager.py
git commit -m "feat: prioritize realtime ASR over TTS"
```

## Task 7: Add TTS REST APIs and Shared Range Responses

**Files:**
- Create: `backend/app/audio/responses.py`
- Create: `backend/app/api/tts.py`
- Modify: `backend/app/api/jobs.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_tts_api.py`
- Modify: `backend/tests/test_jobs_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_clone_voice_requires_consent(client):
    response = client.post(
        "/api/tts/voices/clone",
        files={"file": ("voice.wav", REFERENCE_WAV, "audio/wav")},
        data={"consent": "false"},
    )
    assert response.status_code == 400
    assert "授权" in response.json()["detail"]


def test_create_poll_play_and_download(client, ready_voice):
    created = client.post("/api/tts/jobs", json={"voice_id": ready_voice.id, "text": "您好"})
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert client.get(f"/api/tts/jobs/{job_id}").status_code == 200
    audio = client.get(f"/api/tts/jobs/{job_id}/audio", headers={"Range": "bytes=0-9"})
    assert audio.status_code == 206
    download = client.get(f"/api/tts/jobs/{job_id}/audio?download=true")
    assert "attachment" in download.headers["Content-Disposition"]
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_tts_api.py tests/test_jobs_api.py -q
```

Expected: FAIL because TTS routes do not exist.

- [ ] **Step 3: Implement routes and reusable audio responses**

Add:

```python
@router.post("/voices/clone", response_model=TtsVoiceResponse, status_code=201)
async def clone_voice(
    request: Request,
    file: UploadFile = File(),
    consent: bool = Form(),
) -> TtsVoiceResponse:
    audio = await file.read(MAX_REFERENCE_BYTES + 1)
    return await _manager(request).create_voice(audio, file.filename or "", consent)


@router.post("/jobs", response_model=TtsJobResponse, status_code=202)
async def create_job(request: Request, body: TtsJobRequest) -> TtsJobResponse:
    return await _manager(request).create_job(body.voice_id, body.text)
```

Add status and audio routes. Extract the existing Range parser/streamer from `jobs.py` into `app/audio/responses.py` and use it from both job audio and TTS audio routes. Preserve existing Range behavior tests.

For generated audio responses, set `X-Audio-Origin: ai-generated`, `X-TTS-Model: Fun-CosyVoice3-0.5B-2512`, and use the download filename `ai-generated-{job_id}.wav`. These headers and filename are part of the API contract and must be asserted in `test_tts_api.py`.

- [ ] **Step 4: Run API tests**

```powershell
python -m pytest tests/test_tts_api.py tests/test_jobs_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/audio/responses.py backend/app/api/tts.py backend/app/api/jobs.py backend/app/main.py backend/tests/test_tts_api.py backend/tests/test_jobs_api.py
git commit -m "feat: expose voice cloning TTS APIs"
```

## Task 8: Add the TTS Page and Per-Sentence Synthesis

**Files:**
- Create: `frontend/src/components/TtsPanel.vue`
- Create: `frontend/src/components/TtsPanel.spec.ts`
- Create: `frontend/src/composables/useTts.ts`
- Create: `frontend/src/composables/useTts.spec.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/TranscriptPanel.vue`
- Modify: `frontend/src/components/TranscriptPanel.spec.ts`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing UI and composable tests**

```typescript
it("requires consent before uploading a reference", async () => {
  const wrapper = mount(TtsPanel, { props: EMPTY_TTS_STATE });
  await wrapper.get("input[type='file']").trigger("change");
  expect(wrapper.emitted("clone-voice")).toBeUndefined();
  expect(wrapper.text()).toContain("请先确认声音使用授权");
});


it("polls synthesis and exposes playable audio", async () => {
  vi.mocked(createTtsJob).mockResolvedValue({ job_id: "tts_1", status: "queued" });
  vi.mocked(getTtsJob)
    .mockResolvedValueOnce({ job_id: "tts_1", status: "running" })
    .mockResolvedValueOnce({ job_id: "tts_1", status: "completed" });
  const tts = useTts();
  await tts.synthesize("您好");
  await vi.runAllTimersAsync();
  expect(tts.audioUrl.value).toContain("/api/tts/jobs/tts_1/audio");
});


it("emits transcript text from the sentence speaker icon", async () => {
  const wrapper = mount(TranscriptPanel, { props: transcriptProps });
  await wrapper.get("button[aria-label='朗读本句']").trigger("click");
  expect(wrapper.emitted("synthesize")?.[0]).toEqual([transcriptProps.segments[0].text]);
});
```

- [ ] **Step 2: Run and verify failure**

```powershell
cd frontend
npm test -- --run src/components/TtsPanel.spec.ts src/composables/useTts.spec.ts src/components/TranscriptPanel.spec.ts
```

Expected: FAIL because TTS frontend modules and sentence action do not exist.

- [ ] **Step 3: Implement the TTS workflow**

`useTts` owns the current temporary voice, synthesis job, polling timer, error, and audio URL. Clear stale timers on new jobs and unmount. Keep the reference file only long enough to upload it; do not store raw audio in localStorage.

`TtsPanel` contains a text area, reference upload, consent checkbox, clone status, synthesize button, queue status, audio player, and download button. Use Lucide icons and stable control dimensions. Disable synthesis until a valid voice exists and text is non-empty.

The `TranscriptPanel` sentence action emits text without navigating by itself. `App.vue` stores the text, switches to `tts` mode, and uses the current temporary voice if available. If no voice exists, the text remains populated while the user uploads a reference.

- [ ] **Step 4: Run frontend tests and build**

```powershell
npm test -- --run src/components/TtsPanel.spec.ts src/composables/useTts.spec.ts src/components/TranscriptPanel.spec.ts src/App.spec.ts
npm run build
```

Expected: PASS and build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/TtsPanel.vue frontend/src/components/TtsPanel.spec.ts frontend/src/composables/useTts.ts frontend/src/composables/useTts.spec.ts frontend/src/api/client.ts frontend/src/types.ts frontend/src/App.vue frontend/src/components/TranscriptPanel.vue frontend/src/components/TranscriptPanel.spec.ts frontend/src/styles.css
git commit -m "feat: add voice cloning TTS workspace"
```

## Task 9: Cleanup, End-to-End Verification, and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/DEVELOPMENT.md`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add cleanup lifecycle tests**

Verify application startup marks stale running TTS jobs failed, deletes expired voice/job files and database rows, and application shutdown drains or safely cancels the queue before closing the HTTP client.

- [ ] **Step 2: Run complete automated checks**

```powershell
cd backend
python -m pytest -q
cd ../frontend
npm test -- --run
npm run build
```

Expected: all tests PASS and build succeeds.

- [ ] **Step 3: Run a real CosyVoice smoke test**

Using the pinned worker and downloaded model:

1. Upload an authorized 8-15 second Mandarin reference.
2. Confirm ASR produces non-empty prompt text.
3. Synthesize a short Chinese sentence.
4. Verify the WAV is non-empty, playable, downloadable, and contains no NaN samples.
5. Confirm worker logs contain job IDs and duration only, not text or paths.

- [ ] **Step 4: Verify realtime priority and browser behavior**

Start a realtime ASR session, submit TTS, and confirm TTS remains queued while partial ASR continues. End realtime input and confirm TTS begins automatically. Test desktop and mobile widths, download, expired voice handling, permission errors, and zero browser console errors.

- [ ] **Step 5: Document operations and commit**

Document pinned setup, separate Python 3.10 worker environment, model disk requirements, start order, health checks, all TTS APIs, limits, 7-day retention, authorization requirement, and upgrade procedure. Then commit:

```powershell
git add README.md docs/API.md docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/DEVELOPMENT.md backend/app/main.py backend/tests
git commit -m "docs: complete CosyVoice TTS operations"
```

## Completion Criteria

- Reference upload requires explicit consent and accepts only supported 3-30 second files under 20 MB.
- Existing ASR produces non-empty `prompt_text`; silent references are rejected.
- Official pinned Fun-CosyVoice3 worker loads once in an isolated Python 3.10 environment.
- Synthesis tasks accept at most 2,000 Chinese characters and expose queue/running/completed/failed states.
- Active realtime ASR keeps new TTS jobs queued; TTS resumes automatically afterward.
- Generated audio supports Range playback and explicit download.
- Reference audio, temporary voice data, and generated output expire after 7 days.
- Per-sentence synthesis preloads text and reuses the current temporary voice.
- Unit, integration, real-model smoke, browser, and production build checks pass.
