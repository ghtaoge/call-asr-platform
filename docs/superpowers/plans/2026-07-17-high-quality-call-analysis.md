# High-Quality Call Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a background-job call analysis workflow that turns dual-channel Chinese recordings into timestamped, punctuated sales/customer dialogue with acoustic emotion trends, four-level sensitive-word highlighting, and DeepSeek summaries in a redesigned Vue workbench.

**Architecture:** FastAPI accepts uploaded files or safe remote URLs and persists a lightweight SQLite job before dispatching a single CPU worker. The worker stores the source audio, runs the two channels through a cached FunASR pipeline, enriches atomic segments, persists partial results, and invokes DeepSeek as an isolated final stage. Vue polls job status, fetches the result once, and derives merged dialogue and chart views without rerunning ASR.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, httpx, PyAV, NumPy, FunASR (SenseVoiceSmall, FSMN-VAD, CT-Punc, emotion2vec), Pydantic v2, Vue 3, TypeScript, Vitest, ECharts, pure CSS.

---

## File Map

### Backend files to create

- `backend/app/jobs/__init__.py`: job package marker.
- `backend/app/jobs/models.py`: job enums and API contracts.
- `backend/app/jobs/repository.py`: SQLite job persistence and restart recovery.
- `backend/app/jobs/storage.py`: per-job source audio storage and retention cleanup.
- `backend/app/jobs/manager.py`: background task ownership, progress transitions, and failure isolation.
- `backend/app/audio/downloader.py`: SSRF-aware streaming URL downloader.
- `backend/app/asr/model_registry.py`: lazy, process-wide FunASR model cache.
- `backend/app/emotion/acoustic_provider.py`: emotion2vec adapter and valence normalization.
- `backend/app/sessions/pipeline.py`: dual-channel transcription, ordering, and enrichment.
- `backend/app/summary/deepseek.py`: official DeepSeek API client and validated summary generation.
- `backend/app/api/jobs.py`: upload, URL, status, result, audio, and summary-retry routes.

### Backend files to modify

- `backend/app/core/config.py`: job, model, downloader, and DeepSeek settings.
- `backend/app/core/models.py`: atomic segment emotion data and summary overview.
- `backend/app/asr/sensevoice_provider.py`: parse FunASR sentence output instead of one fake-duration segment.
- `backend/app/audio/preprocessor.py`: reject non-stereo jobs and slice channel WAV by timestamp.
- `backend/app/main.py`: lifespan initialization and jobs router.
- `backend/app/api/offline.py`: legacy synchronous compatibility through the job manager.
- `backend/app/api/url.py`: legacy URL compatibility through the safe downloader/job manager.
- `backend/app/sessions/repository.py`: deterministic segment ordering and artifact reads.
- `backend/pyproject.toml`: declare model/test dependencies actually used.
- `.env.example`: document runtime configuration.

### Frontend files to create

- `frontend/src/composables/useAnalysisJob.ts`: job submission and polling state machine.
- `frontend/src/components/JobProgress.vue`: stable processing-stage progress bar.
- `frontend/src/components/AudioPlayer.vue`: local job audio player and seek API.
- `frontend/src/components/AnalysisPanel.vue`: summary/risk/emotion tabs.
- `frontend/src/components/SummaryPanel.vue`: DeepSeek summary rendering and retry.
- `frontend/src/components/SensitivePanel.vue`: four-level risk totals and navigation.
- `frontend/src/components/EmotionChart.vue`: ECharts dual-speaker trend.
- `frontend/src/utils/transcript.ts`: deterministic client-side merged view.
- `frontend/src/utils/emotion.ts`: chart series construction.

### Frontend files to modify

- `frontend/src/types.ts`: job/result/emotion/summary contracts.
- `frontend/src/api/client.ts`: job API methods.
- `frontend/src/components/Toolbar.vue`: remove role and realtime controls.
- `frontend/src/components/TranscriptPanel.vue`: filters, modes, seek, and four-level highlighting.
- `frontend/src/App.vue`: orchestrate jobs, player, transcript, and analysis tabs.
- `frontend/src/styles.css`: responsive Chinese workbench design.
- `frontend/src/App.spec.ts`: root workflow tests.
- `frontend/package.json` and `frontend/package-lock.json`: add ECharts.

---

### Task 1: Runtime Settings and Shared Contracts

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/models.py`
- Modify: `backend/app/emotion/provider.py`
- Create: `backend/app/jobs/__init__.py`
- Create: `backend/app/jobs/models.py`
- Test: `backend/tests/test_job_models.py`

- [ ] **Step 1: Write failing contract tests**

```python
from app.core.config import Settings
from app.core.models import CallSummary, EmotionResult
from app.jobs.models import JobStage, JobStatus, JobStatusResponse, SummaryStatus


def test_analysis_contracts_have_job_and_emotion_fields(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert settings.jobs_dir == tmp_path / "jobs"
    assert settings.deepseek_model == "deepseek-v4-pro"
    emotion = EmotionResult(label="angry", confidence=0.8, score=-0.8)
    assert emotion.score == -0.8
    summary = CallSummary(overview="客户要求退款")
    assert summary.overview == "客户要求退款"
    status = JobStatusResponse(
        job_id="job_1",
        session_id="call_1",
        status=JobStatus.running,
        stage=JobStage.transcribing_sales,
        progress=15,
        summary_status=SummaryStatus.pending,
    )
    assert status.progress == 15
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && python -m pytest tests/test_job_models.py -q`

Expected: FAIL because job contracts and new settings do not exist.

- [ ] **Step 3: Add settings and exact Pydantic contracts**

Add application settings with the existing `CALL_ASR_` prefix and explicit canonical `DEEPSEEK_*` aliases (also accepting prefixed aliases for backward compatibility):

```python
from pydantic import AliasChoices, Field


class Settings(BaseSettings):
    app_name: str = "Call ASR Platform"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/call_asr.sqlite3")
    sensitive_words_path: Path = Path("data/sensitive_words.sample.json")
    preferred_device: str = "auto"
    max_audio_bytes: int = 50 * 1024 * 1024
    download_timeout_seconds: float = 30.0
    job_retention_days: int = 7
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "CALL_ASR_DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "CALL_ASR_DEEPSEEK_BASE_URL"),
    )
    deepseek_model: str = Field(
        default="deepseek-v4-pro",
        validation_alias=AliasChoices("DEEPSEEK_MODEL", "CALL_ASR_DEEPSEEK_MODEL"),
    )
    deepseek_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("DEEPSEEK_TIMEOUT_SECONDS", "CALL_ASR_DEEPSEEK_TIMEOUT_SECONDS"),
    )

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"
```

Change `EmotionResult` and `CallSummary`:

```python
class EmotionResult(BaseModel):
    label: Literal["positive", "neutral", "negative", "angry", "anxious"]
    confidence: float = Field(default=0.5, ge=0, le=1)
    score: float = Field(default=0.0, ge=-1, le=1)


class CallSummary(BaseModel):
    overview: str = ""
    customer_needs: list[str] = Field(default_factory=list)
    sales_promises: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    follow_up_items: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
```

Update the legacy `RuleEmotionProvider` at the same time so its old realtime path uses the new semantics. Each branch sets both confidence and valence, for example:

```python
if any(word in text for word in angry_words):
    return EmotionResult(label="angry", confidence=0.86, score=-0.86)
if any(word in text for word in positive_words):
    return EmotionResult(label="positive", confidence=0.72, score=0.72)
return EmotionResult(label="neutral", confidence=0.62, score=0.0)
```

Create job enums and responses:

```python
from enum import StrEnum
from pydantic import BaseModel, Field
from app.core.models import CallSummary, QualityScore, Segment


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class JobStage(StrEnum):
    queued = "queued"
    preparing_audio = "preparing_audio"
    transcribing_sales = "transcribing_sales"
    transcribing_customer = "transcribing_customer"
    merging_segments = "merging_segments"
    analyzing_emotion = "analyzing_emotion"
    scanning_risks = "scanning_risks"
    generating_summary = "generating_summary"
    completed = "completed"
    failed = "failed"


class SummaryStatus(StrEnum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class JobCreateResponse(BaseModel):
    job_id: str
    session_id: str
    status: JobStatus
    stage: JobStage
    progress: int = Field(ge=0, le=100)


class JobStatusResponse(JobCreateResponse):
    summary_status: SummaryStatus
    error_code: str | None = None
    error_message: str | None = None


class JobRecord(JobStatusResponse):
    source_type: str
    source_url: str | None = None
    source_path: str | None = None
    source_content_type: str | None = None
    created_at: str
    updated_at: str


class JobAnalysisResponse(BaseModel):
    job_id: str
    session_id: str
    summary_status: SummaryStatus
    summary_error_code: str | None = None
    segments: list[Segment]
    quality: QualityScore
    summary: CallSummary | None = None
```

- [ ] **Step 4: Update existing emotion fixtures and run contract tests**

Replace old `EmotionResult(label=..., score=confidence)` fixtures with explicit `confidence` and valence `score`. Run:

`cd backend && python -m pytest tests/test_job_models.py tests/test_insights.py tests/test_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/app/core/models.py backend/app/emotion/provider.py backend/app/jobs backend/tests/test_job_models.py backend/tests/test_insights.py backend/tests/test_repository.py
git commit -m "feat: define call analysis job contracts"
```

### Task 2: Job Repository and Audio Storage

**Files:**
- Create: `backend/app/jobs/repository.py`
- Create: `backend/app/jobs/storage.py`
- Test: `backend/tests/test_job_repository.py`
- Test: `backend/tests/test_job_storage.py`

- [ ] **Step 1: Write failing repository and storage tests**

```python
import os
from datetime import UTC, datetime, timedelta
from app.jobs.models import JobStage, JobStatus, SummaryStatus
from app.jobs.repository import JobRepository
from app.jobs.storage import JobStorage


async def test_job_repository_persists_progress_and_recovers_running_jobs(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    await repo.init()
    await repo.create("job_1", "call_1", "upload")
    await repo.update_progress("job_1", JobStage.transcribing_sales, 15)
    job = await repo.get("job_1")
    assert job.status == JobStatus.running
    assert job.progress == 15
    assert await repo.mark_running_interrupted() == 1
    assert (await repo.get("job_1")).status == JobStatus.interrupted


def test_job_storage_saves_source_and_removes_expired_jobs(tmp_path):
    storage = JobStorage(tmp_path, retention_days=7)
    path = storage.save_bytes("job_1", b"RIFFdata", "audio/wav")
    assert path.read_bytes() == b"RIFFdata"
    old = datetime.now(UTC) - timedelta(days=8)
    timestamp = old.timestamp()
    os.utime(path.parent, (timestamp, timestamp))
    assert storage.cleanup_expired() == ["job_1"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_job_repository.py tests/test_job_storage.py -q`

Expected: FAIL because repository and storage classes do not exist.

- [ ] **Step 3: Implement SQLite job persistence**

Use parameterized SQL and one row per job:

```python
CREATE_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_path TEXT,
    source_content_type TEXT,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL,
    summary_status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
```

`create()` writes `queued/queued/0/pending`. `update_progress()` atomically sets `status='running'`, stage, progress, and `updated_at`. Add `set_source()`, `complete()`, `fail()`, `set_summary_status()`, `get()`, `delete(job_id)`, and `mark_running_interrupted()`.

- [ ] **Step 4: Implement bounded filesystem storage**

`JobStorage.save_stream()` must write to a temporary file, count bytes while writing, `os.replace()` only after success, and delete partial files on any exception. Store metadata in the repository only after the final path exists. `cleanup_expired()` resolves every candidate path and verifies it is a child of `jobs_dir` before recursive deletion.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_job_repository.py tests/test_job_storage.py -q`

Expected: PASS.

```bash
git add backend/app/jobs/repository.py backend/app/jobs/storage.py backend/tests/test_job_repository.py backend/tests/test_job_storage.py
git commit -m "feat: persist analysis jobs and source audio"
```

### Task 3: Safe Remote Audio Downloader

**Files:**
- Create: `backend/app/audio/downloader.py`
- Test: `backend/tests/test_audio_downloader.py`

- [ ] **Step 1: Write failing URL safety tests**

```python
import httpx
import pytest
from app.audio.downloader import DownloadError, SafeAudioDownloader


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://127.0.0.1/audio.wav",
    "http://169.254.169.254/latest/meta-data",
    "http://user:pass@example.com/audio.wav",
])
def test_downloader_rejects_unsafe_urls(url, tmp_path):
    downloader = SafeAudioDownloader(max_bytes=1024, timeout=2)
    with pytest.raises(DownloadError) as exc:
        downloader.download(url, tmp_path / "source")
    assert exc.value.code == "blocked_url" or exc.value.code == "invalid_url"


def test_downloader_validates_every_redirect_and_limits_body(tmp_path):
    def handler(request: httpx.Request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        return httpx.Response(200, content=b"x" * 2048, headers={"content-type": "audio/wav"})

    downloader = SafeAudioDownloader(
        max_bytes=1024,
        timeout=2,
        transport=httpx.MockTransport(handler),
        resolver=lambda host: ["93.184.216.34"],
    )
    with pytest.raises(DownloadError) as exc:
        downloader.download("https://example.com/start", tmp_path / "source")
    assert exc.value.code == "blocked_url"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && python -m pytest tests/test_audio_downloader.py -q`

Expected: FAIL because `SafeAudioDownloader` does not exist.

- [ ] **Step 3: Implement validation and manual redirects**

Use `urllib.parse.urlsplit`, `socket.getaddrinfo`, and `ipaddress.ip_address`. Require `http` or `https`, reject embedded credentials, require a hostname, and reject every resolved IP for which `is_global` is false. Set `follow_redirects=False`; for at most five redirects, resolve and validate the new target before requesting it.

Stream response bytes to `destination.with_suffix('.part')`, stop before exceeding `max_bytes`, require an audio-like content type, and atomically rename the completed file. Raise `DownloadError(code, public_message)` without including the signed query string.

- [ ] **Step 4: Run positive, redirect, timeout, and limit tests**

Run: `cd backend && python -m pytest tests/test_audio_downloader.py -q`

Expected: PASS with cases for success, unsafe hosts, unsafe redirects, timeout, non-audio content, and oversized bodies.

- [ ] **Step 5: Commit**

```bash
git add backend/app/audio/downloader.py backend/tests/test_audio_downloader.py
git commit -m "feat: download remote audio with SSRF guards"
```

### Task 4: Cached FunASR Registry and Sentence Parsing

**Files:**
- Create: `backend/app/asr/model_registry.py`
- Modify: `backend/app/asr/sensevoice_provider.py`
- Test: `backend/tests/test_sensevoice_provider.py`
- Test: `backend/tests/test_model_registry.py`

- [ ] **Step 1: Write failing sentence and cache tests**

```python
from app.asr.model_registry import ModelRegistry
from app.asr.sensevoice_provider import SenseVoiceProvider
from app.core.models import Speaker


class FakeSenseVoice:
    def generate(self, **kwargs):
        return [{
            "text": "完整文本",
            "sentence_info": [
                {"start": 600, "end": 1500, "text": "您好。"},
                {"start": 1800, "end": 3200, "sentence": "请问需要什么？"},
            ],
        }]


def test_sensevoice_returns_atomic_timestamped_segments(tmp_path):
    provider = SenseVoiceProvider(model=FakeSenseVoice())
    segments = provider.transcribe_file(str(tmp_path / "channel.wav"), "call_1", Speaker.sales)
    assert [(s.start_ms, s.end_ms, s.text) for s in segments] == [
        (600, 1500, "您好。"),
        (1800, 3200, "请问需要什么？"),
    ]
    assert all(s.speaker == Speaker.sales for s in segments)


def test_registry_loads_each_model_once(monkeypatch):
    calls = []
    monkeypatch.setattr("app.asr.model_registry.AutoModel", lambda **kw: calls.append(kw) or object())
    registry = ModelRegistry(device="cpu")
    assert registry.sensevoice() is registry.sensevoice()
    assert len(calls) == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_sensevoice_provider.py tests/test_model_registry.py -q`

Expected: FAIL because dependency injection, file transcription, and registry do not exist.

- [ ] **Step 3: Implement the process-wide model registry**

Use a `threading.Lock` around lazy creation. Construct the ASR pipeline exactly once:

```python
self._sensevoice = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",
    punc_model="ct-punc",
    vad_kwargs={"max_single_segment_time": 30_000},
    device=self.device,
    trust_remote_code=True,
    disable_update=True,
)
```

Expose `sensevoice()` and later `emotion()` methods. Do not instantiate models in FastAPI route functions.

- [ ] **Step 4: Parse `sentence_info` without heuristic punctuation**

Add `transcribe_file(path, session_id, speaker)`. Call `generate(input=path, language='zh', use_itn=True, merge_vad=False, batch_size_s=60)`. For each sentence, read `text` then `sentence` as fallback, strip SenseVoice tags, validate `0 <= start < end`, and create one Segment. Use the top-level text only as a fallback when `sentence_info` is absent. Remove `add_basic_punctuation()` from this provider.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_sensevoice_provider.py tests/test_model_registry.py tests/test_audio_conversion.py -q`

Expected: PASS.

```bash
git add backend/app/asr/model_registry.py backend/app/asr/sensevoice_provider.py backend/tests/test_sensevoice_provider.py backend/tests/test_model_registry.py
git commit -m "feat: return timestamped FunASR sentence segments"
```

### Task 5: Strict Stereo Preparation and Time-Based Merge

**Files:**
- Modify: `backend/app/audio/preprocessor.py`
- Create: `backend/app/sessions/pipeline.py`
- Test: `backend/tests/test_analysis_pipeline.py`

- [ ] **Step 1: Write failing stereo and merge tests**

```python
import pytest
from app.audio.preprocessor import AudioPreprocessor, UnsupportedChannelLayout
from app.core.models import Segment, Speaker
from app.sessions.pipeline import merge_channel_segments


def segment(id, speaker, start, end, text):
    return Segment(id=id, session_id="call_1", speaker=speaker, start_ms=start, end_ms=end, text=text)


def test_merge_channel_segments_interleaves_by_real_time():
    sales = [segment("s1", Speaker.sales, 0, 1000, "您好。"), segment("s2", Speaker.sales, 4000, 5000, "可以。")]
    customer = [segment("c1", Speaker.customer, 1200, 2500, "我要退款。")]
    assert [s.id for s in merge_channel_segments(sales, customer)] == ["s1", "c1", "s2"]


def test_pipeline_rejects_mono_audio(mono_wav_bytes):
    with pytest.raises(UnsupportedChannelLayout):
        AudioPreprocessor().split_required_stereo(mono_wav_bytes)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_analysis_pipeline.py -q`

Expected: FAIL because strict stereo and merge functions do not exist.

- [ ] **Step 3: Add strict stereo preparation**

Keep existing `split_channels()` for legacy callers. Add `split_required_stereo()` that calls it and raises `UnsupportedChannelLayout("双声道录音才能区分销售和客户")` when `is_stereo` is false. Write the generated channel WAV bytes to the job directory as `sales.wav` and `customer.wav` so ASR and emotion can reuse them.

- [ ] **Step 4: Add deterministic time merge and pipeline shell**

```python
def merge_channel_segments(sales, customer):
    return sorted(
        [*sales, *customer],
        key=lambda item: (item.start_ms, item.end_ms, item.speaker.value),
    )
```

Create `AnalysisPipeline.transcribe(job_dir, session_id, progress)` that prepares stereo files, reports `transcribing_sales`, transcribes sales, reports `transcribing_customer`, transcribes customer, then reports `merging_segments` and returns the merged list.

Define the constructor and local result contract at creation time so later tasks use stable names:

```python
@dataclass(frozen=True)
class LocalAnalysisResult:
    segments: list[Segment]
    quality: QualityScore


class AnalysisPipeline:
    def __init__(self, audio, asr, emotion, sensitive_store, compliance, quality):
        self.audio = audio
        self.asr = asr
        self.emotion = emotion
        self.sensitive_store = sensitive_store
        self.compliance = compliance
        self.quality = quality
```

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_analysis_pipeline.py tests/test_audio_conversion.py -q`

Expected: PASS.

```bash
git add backend/app/audio/preprocessor.py backend/app/sessions/pipeline.py backend/tests/test_analysis_pipeline.py
git commit -m "feat: merge dual-channel dialogue by timestamp"
```

### Task 6: Acoustic Emotion Provider

**Files:**
- Create: `backend/app/emotion/acoustic_provider.py`
- Modify: `backend/app/asr/model_registry.py`
- Modify: `backend/app/audio/preprocessor.py`
- Test: `backend/tests/test_acoustic_emotion.py`

- [ ] **Step 1: Write failing normalization and slicing tests**

```python
from app.emotion.acoustic_provider import AcousticEmotionProvider


class FakeEmotionModel:
    def generate(self, **kwargs):
        return [{"labels": ["生气/angry", "中立/neutral"], "scores": [0.8, 0.2]}]


def test_acoustic_emotion_normalizes_label_confidence_and_valence(wav_bytes):
    provider = AcousticEmotionProvider(FakeEmotionModel())
    result = provider.analyze(wav_bytes, start_ms=500, end_ms=1500)
    assert result.label == "angry"
    assert result.confidence == 0.8
    assert result.score == -0.8


def test_unknown_low_confidence_emotion_is_neutral(wav_bytes):
    model = lambda: None
    model.generate = lambda **kw: [{"labels": ["unknown"], "scores": [0.2]}]
    result = AcousticEmotionProvider(model).analyze(wav_bytes, 0, 500)
    assert result.label == "neutral"
    assert result.score == 0
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_acoustic_emotion.py -q`

Expected: FAIL because acoustic provider does not exist.

- [ ] **Step 3: Cache emotion2vec and slice WAV intervals**

Add registry creation:

```python
AutoModel(model="iic/emotion2vec_plus_large", device=self.device, disable_update=True)
```

Add `AudioPreprocessor.slice_wav(wav_bytes, start_ms, end_ms)` using the standard `wave` module. Clamp indices to available frames and raise on empty ranges.

- [ ] **Step 4: Normalize model results**

Map label aliases to product labels and base valence:

```python
VALENCE = {
    "positive": 1.0,
    "neutral": 0.0,
    "negative": -0.65,
    "angry": -1.0,
    "anxious": -0.8,
}
```

Choose the highest-score label, require confidence at least 0.35, and return `score=round(VALENCE[label] * confidence, 4)`. Never infer emotion from transcript keywords in the new pipeline.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_acoustic_emotion.py -q`

Expected: PASS.

```bash
git add backend/app/emotion/acoustic_provider.py backend/app/asr/model_registry.py backend/app/audio/preprocessor.py backend/tests/test_acoustic_emotion.py
git commit -m "feat: analyze segment emotion from acoustic audio"
```

### Task 7: Segment Enrichment, Risks, and Quality

**Files:**
- Modify: `backend/app/sessions/pipeline.py`
- Modify: `backend/app/quality/scoring.py`
- Test: `backend/tests/test_analysis_enrichment.py`
- Test: `backend/tests/test_insights.py`

- [ ] **Step 1: Write a failing enriched-pipeline test**

```python
from app.core.models import EmotionResult, RiskLevel, SensitiveHit, Speaker
from app.sessions.pipeline import AnalysisPipeline


class FakeEmotion:
    def analyze(self, wav, start_ms, end_ms):
        return EmotionResult(label="negative", confidence=0.8, score=-0.52)


class FakeSensitiveStore:
    def scan(self, text, speaker, segment_id, start_ms, end_ms):
        if "退款" not in text:
            return []
        return [SensitiveHit(
            word="退款", level=RiskLevel.critical, category="售后",
            start=text.index("退款"), end=text.index("退款") + 2,
            context=text, speaker=speaker, segment_id=segment_id,
            start_ms=start_ms, end_ms=end_ms,
        )]


def test_pipeline_enriches_each_segment_without_translation(
    stereo_wav_bytes, fake_asr, fake_compliance, quality_scorer
):
    pipeline = AnalysisPipeline(
        audio=AudioPreprocessor(),
        asr=fake_asr,
        emotion=FakeEmotion(),
        sensitive_store=FakeSensitiveStore(),
        compliance=fake_compliance,
        quality=quality_scorer,
    )
    result = pipeline.run(stereo_wav_bytes, "call_1", lambda stage, progress: None)
    assert [segment.speaker for segment in result.segments] == [Speaker.sales, Speaker.customer]
    assert result.segments[0].translation == ""
    assert result.segments[0].emotion.confidence > 0
    assert result.segments[1].sensitive_hits[0].level == RiskLevel.critical
    assert result.quality.customer_talk_ratio > 0
```

Define the fixtures in the same test module:

```python
import io
import wave
import numpy as np
import pytest
from app.audio.preprocessor import AudioPreprocessor
from app.core.models import Segment
from app.quality.scoring import QualityScorer


@pytest.fixture
def stereo_wav_bytes():
    samples = np.zeros((16_000, 2), dtype=np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(samples.tobytes())
    return buffer.getvalue()


@pytest.fixture
def fake_asr():
    class FakeAsr:
        def transcribe_file(self, path, session_id, speaker):
            if speaker == Speaker.sales:
                return [Segment(id="s1", session_id=session_id, speaker=speaker,
                                start_ms=0, end_ms=1000, text="您好。")]
            return [Segment(id="c1", session_id=session_id, speaker=speaker,
                            start_ms=1200, end_ms=2500, text="我要退款。")]
    return FakeAsr()


@pytest.fixture
def fake_compliance():
    class FakeCompliance:
        def check(self, segment):
            return []
    return FakeCompliance()


@pytest.fixture
def quality_scorer():
    return QualityScorer()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && python -m pytest tests/test_analysis_enrichment.py -q`

Expected: FAIL because the pipeline only transcribes and merges.

- [ ] **Step 3: Enrich atomic segments in processing order**

After merge, report `analyzing_emotion` and analyze each segment against its own speaker-channel WAV. Then report `scanning_risks`; set `translation=""`, scan the existing sensitive store, run compliance rules, and compute quality from real segment durations. Keep sensitive-word character positions relative to each atomic segment.

- [ ] **Step 4: Count overlap-based interruptions**

Update quality scoring to count a transition as an interruption when a segment begins before the other speaker's current segment ends. Test overlapping and non-overlapping pairs; do not infer interruption from text.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_analysis_enrichment.py tests/test_insights.py tests/test_sensitive.py -q`

Expected: PASS.

```bash
git add backend/app/sessions/pipeline.py backend/app/quality/scoring.py backend/tests/test_analysis_enrichment.py backend/tests/test_insights.py
git commit -m "feat: enrich atomic call segments with emotion and risk"
```

### Task 8: DeepSeek Summary Provider

**Files:**
- Create: `backend/app/summary/deepseek.py`
- Test: `backend/tests/test_deepseek_summary.py`

- [ ] **Step 1: Write failing success and failure-isolation tests**

```python
import httpx
import pytest
from app.core.models import Segment, Speaker
from app.summary.deepseek import DeepSeekSummaryProvider, SummaryError


def transcript_segments():
    return [
        Segment(id="s1", session_id="call_1", speaker=Speaker.customer,
                start_ms=1000, end_ms=2500, text="我要退款。")
    ]


async def test_deepseek_returns_validated_structured_summary():
    payload = '{"overview":"客户要求退款","customer_needs":["退款"],"sales_promises":[],"risk_points":[],"follow_up_items":["核对订单"],"next_steps":["回电"]}'
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": payload}}]}))
    provider = DeepSeekSummaryProvider("key", "https://api.deepseek.com", "deepseek-v4-pro", transport=transport)
    summary = await provider.generate(transcript_segments())
    assert summary.overview == "客户要求退款"
    assert summary.customer_needs == ["退款"]


async def test_missing_api_key_is_a_summary_only_error():
    provider = DeepSeekSummaryProvider(None, "https://api.deepseek.com", "deepseek-v4-pro")
    with pytest.raises(SummaryError) as exc:
        await provider.generate(transcript_segments())
    assert exc.value.code == "summary_missing_api_key"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_deepseek_summary.py -q`

Expected: FAIL because the provider does not exist.

- [ ] **Step 3: Implement the official API client**

Use `httpx.AsyncClient(base_url=..., timeout=...)` and `POST /chat/completions` with Bearer authentication. Build transcript input as lines like `[00:12.300-00:14.900][客户] 我要退款。`. Request model `deepseek-v4-pro` from configuration and require a JSON object with exactly the `CallSummary` fields.

Define a stable public exception contract used by the job manager:

```python
class SummaryError(RuntimeError):
    def __init__(self, code: str, public_message: str):
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
```

Strip one optional Markdown JSON fence, parse with `json.loads`, then validate with `CallSummary.model_validate`. On parse/validation failure, send one repair request containing the validation errors and the invalid response; never retry network timeouts automatically.

- [ ] **Step 4: Add long-call chunking and error mapping tests**

Split input by whole segment lines into chunks of at most 12,000 Chinese characters. Summarize chunks first, then send only validated chunk summaries for final synthesis. Add tests for timeout, HTTP 429, invalid JSON twice, and long transcript chunk count. Map them to stable public error codes.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_deepseek_summary.py -q`

Expected: PASS.

```bash
git add backend/app/summary/deepseek.py backend/tests/test_deepseek_summary.py
git commit -m "feat: generate validated DeepSeek call summaries"
```

### Task 9: Background Job Manager

**Files:**
- Create: `backend/app/jobs/manager.py`
- Modify: `backend/app/sessions/repository.py`
- Test: `backend/tests/test_job_manager.py`

- [ ] **Step 1: Write failing lifecycle and partial-success tests**

```python
from app.core.models import CallSummary, EmotionResult, QualityScore, Segment, Speaker
from app.jobs.manager import JobManager
from app.jobs.models import JobStage, JobStatus, SummaryStatus
from app.jobs.repository import JobRepository
from app.jobs.storage import JobStorage
from app.sessions.pipeline import LocalAnalysisResult
from app.sessions.repository import SessionRepository
from app.summary.deepseek import SummaryError


class FakePipeline:
    def run(self, audio, session_id, progress):
        progress(JobStage.transcribing_sales, 15)
        segment = Segment(
            id=f"{session_id}_s1", session_id=session_id, speaker=Speaker.sales,
            start_ms=0, end_ms=1000, text="您好。",
            emotion=EmotionResult(label="neutral", confidence=0.9, score=0),
        )
        quality = QualityScore(
            score=90, noise_level="low", silence_ratio=0.1,
            sales_talk_ratio=1, customer_talk_ratio=0, interruptions=0,
            negative_emotion_ratio=0, risk_hit_count=0, suggestions=[],
        )
        return LocalAnalysisResult([segment], quality)


class FakeSummary:
    async def generate(self, segments):
        return CallSummary(overview="销售已问候客户")


class FailingSummary:
    async def generate(self, segments):
        raise SummaryError("summary_timeout", "摘要生成超时")


async def build_manager(tmp_path, summary):
    job_repo = JobRepository(tmp_path / "jobs.sqlite3")
    session_repo = SessionRepository(tmp_path / "sessions.sqlite3")
    await job_repo.init()
    await session_repo.init()
    manager = JobManager(
        jobs=job_repo,
        sessions=session_repo,
        storage=JobStorage(tmp_path / "job-files", retention_days=7),
        pipeline=FakePipeline(),
        summary=summary,
        downloader=None,
    )
    return manager, job_repo


async def test_manager_persists_progress_and_completed_result(tmp_path):
    manager, job_repo = await build_manager(tmp_path, FakeSummary())
    job = await manager.create_upload(b"audio", "audio/wav")
    await manager.wait(job.job_id)
    status = await job_repo.get(job.job_id)
    assert status.status == JobStatus.completed
    assert status.progress == 100
    assert status.summary_status == SummaryStatus.completed


async def test_summary_failure_does_not_fail_local_analysis(tmp_path):
    manager, job_repo = await build_manager(tmp_path, FailingSummary())
    job = await manager.create_upload(b"audio", "audio/wav")
    await manager.wait(job.job_id)
    status = await job_repo.get(job.job_id)
    assert status.status == JobStatus.completed
    assert status.summary_status == SummaryStatus.failed


async def test_retry_summary_uses_persisted_segments(tmp_path):
    manager, job_repo = await build_manager(tmp_path, FailingSummary())
    job = await manager.create_upload(b"audio", "audio/wav")
    await manager.wait(job.job_id)
    manager.summary = FakeSummary()
    await manager.retry_summary(job.job_id)
    await manager.wait(job.job_id)
    assert (await job_repo.get(job.job_id)).summary_status == SummaryStatus.completed
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_job_manager.py -q`

Expected: FAIL because manager does not exist.

- [ ] **Step 3: Implement owned background tasks and one CPU worker**

`JobManager(jobs, sessions, storage, pipeline, summary, downloader)` owns `ThreadPoolExecutor(max_workers=1)` and a `set[asyncio.Task]`. `create_upload()` persists audio then schedules `_run_local_analysis()`. `create_url()` schedules download first, stores only `scheme://host/path` as display metadata (never query or fragment), saves the downloaded source metadata, then uses the same local path. Keep a strong reference to every task and remove it in a done callback. Expose `wait(job_id)` for compatibility routes and tests; it awaits the owned task but does not remove persisted results.

Run the synchronous `AnalysisPipeline.run()` via `asyncio.get_running_loop().run_in_executor`. Progress callbacks use `asyncio.run_coroutine_threadsafe(job_repo.update_progress(...), loop)` and wait on that returned future before continuing, so persisted stages cannot arrive out of order during CPU work.

- [ ] **Step 4: Isolate summary and persist readable results**

After local analysis, save deterministic segment order, quality, and local rule artifacts. Run DeepSeek asynchronously. A summary error updates only `summary_status` and its error fields; local job status becomes completed. Implement `retry_summary(job_id)` using existing persisted segments and reject retries while one is already running.

Add `SessionRepository.get_quality()` and `get_summary()` artifact readers. Change `list_segments()` to parse rows and return `sorted(segments, key=lambda s: (s.start_ms, s.end_ms, s.speaker.value))` instead of relying on lexicographic IDs. `JobManager.get_result()` builds `JobAnalysisResponse` only from these persisted readers so process memory is not the source of truth.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_job_manager.py tests/test_repository.py -q`

Expected: PASS.

```bash
git add backend/app/jobs/manager.py backend/app/sessions/repository.py backend/tests/test_job_manager.py
git commit -m "feat: run call analysis as persistent background jobs"
```

### Task 10: Job API and Range Audio Playback

**Files:**
- Create: `backend/app/api/jobs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_jobs_api.py`
- Test: `backend/tests/test_audio_range_api.py`

- [ ] **Step 1: Write failing API tests**

```python
from fastapi.testclient import TestClient
from app.jobs.models import JobCreateResponse, JobStage, JobStatus, JobStatusResponse, SummaryStatus
from app.main import create_app


class FakeManager:
    def __init__(self, audio_path=None):
        self.audio_path = audio_path

    async def create_upload(self, audio, content_type):
        return JobCreateResponse(job_id="job_1", session_id="call_1",
                                 status=JobStatus.queued, stage=JobStage.queued, progress=0)

    async def create_url(self, audio_url):
        return JobCreateResponse(job_id="job_1", session_id="call_1",
                                 status=JobStatus.queued, stage=JobStage.queued, progress=0)

    async def retry_summary(self, job_id):
        return await self.get_status(job_id)

    async def get_status(self, job_id):
        completed = self.audio_path is not None
        return JobStatusResponse(
            job_id=job_id, session_id="call_1",
            status=JobStatus.completed if completed else JobStatus.running,
            stage=JobStage.completed if completed else JobStage.transcribing_sales,
            progress=100 if completed else 15,
            summary_status=SummaryStatus.pending,
        )

    async def get_result(self, job_id):
        raise AssertionError("result must not be loaded before completion")

    async def get_audio(self, job_id):
        return self.audio_path, "audio/wav"


def client_with(manager):
    app = create_app()
    client = TestClient(app)
    client.app.state.job_manager = manager
    return client


def test_upload_creates_accepted_job():
    client = client_with(FakeManager())
    response = client.post("/api/jobs/upload", files={"file": ("call.wav", b"audio", "audio/wav")})
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_url_and_summary_retry_routes_delegate_to_manager():
    client = client_with(FakeManager())
    created = client.post("/api/jobs/url", json={"audio_url": "https://example.com/call.wav"})
    retried = client.post("/api/jobs/job_1/retry-summary")
    assert created.status_code == 202
    assert retried.status_code == 202


def test_status_is_lightweight_and_result_waits_for_completion():
    client = client_with(FakeManager())
    response = client.get("/api/jobs/job_1")
    assert "segments" not in response.json()
    assert client.get("/api/jobs/job_1/result").status_code == 409


def test_audio_endpoint_supports_byte_ranges(tmp_path):
    path = tmp_path / "source.wav"
    path.write_bytes(b"0123456789")
    client = client_with(FakeManager(audio_path=path))
    response = client.get(
        "/api/jobs/job_1/audio",
        headers={"Range": "bytes=0-3"},
    )
    assert response.status_code == 206
    assert response.headers["content-range"].startswith("bytes 0-3/")
    assert len(response.content) == 4
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_jobs_api.py tests/test_audio_range_api.py -q`

Expected: FAIL with 404 routes.

- [ ] **Step 3: Add application lifespan and job routes**

Use an `asynccontextmanager` lifespan to initialize repositories, mark stale running jobs interrupted, clean expired storage, delete each expired ID from the job repository, create one `JobManager`, assign it to `app.state.job_manager`, and close its executor on shutdown. Include `jobs.router`.

Implement upload and URL creation with HTTP 202. Read at most `max_audio_bytes + 1` bytes from `UploadFile`, reject oversized data before scheduling, and close the upload in `finally`. Read the manager from `request.app.state` so tests can inject a fake manager. Status returns `JobStatusResponse`; result returns 409 until local analysis is complete.

- [ ] **Step 4: Implement safe Range responses**

Parse only one `bytes=start-end` range. Validate bounds against file size, return 416 for invalid ranges, seek and stream exactly the requested bytes, and include `Accept-Ranges`, `Content-Range`, `Content-Length`, and the stored media type. Return 409 before source preparation and 404 for missing/expired files.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_jobs_api.py tests/test_audio_range_api.py tests/test_health.py -q`

Expected: PASS.

```bash
git add backend/app/api/jobs.py backend/app/main.py backend/tests/test_jobs_api.py backend/tests/test_audio_range_api.py
git commit -m "feat: expose background analysis job API"
```

### Task 11: Legacy Endpoint Compatibility

**Files:**
- Modify: `backend/app/api/offline.py`
- Modify: `backend/app/api/url.py`
- Modify: `backend/app/sessions/service.py`
- Test: `backend/tests/test_offline_api.py`
- Test: `backend/tests/test_url_api.py`

- [ ] **Step 1: Replace invalid fake-audio tests with injected manager tests**

```python
from fastapi.testclient import TestClient
from app.core.models import CallSummary, EmotionResult, QualityScore, Segment, Speaker
from app.jobs.models import JobAnalysisResponse, JobCreateResponse, JobStage, JobStatus, SummaryStatus
from app.main import create_app


class CompatibilityManager:
    async def create_upload(self, audio, content_type):
        return JobCreateResponse(job_id="job_1", session_id="call_1",
                                 status=JobStatus.queued, stage=JobStage.queued, progress=0)

    async def wait(self, job_id):
        return None

    async def get_result(self, job_id):
        segment = Segment(
            id="s1", session_id="call_1", speaker=Speaker.sales,
            start_ms=0, end_ms=1000, text="您好。", translation="",
            emotion=EmotionResult(label="neutral", confidence=0.9, score=0),
        )
        quality = QualityScore(
            score=90, noise_level="low", silence_ratio=0.1,
            sales_talk_ratio=1, customer_talk_ratio=0, interruptions=0,
            negative_emotion_ratio=0, risk_hit_count=0, suggestions=[],
        )
        return JobAnalysisResponse(
            job_id=job_id, session_id="call_1", summary_status=SummaryStatus.completed,
            segments=[segment], quality=quality, summary=CallSummary(overview="已问候"),
        )


def test_legacy_offline_waits_for_job_and_returns_old_shape():
    app = create_app()
    client = TestClient(app)
    client.app.state.job_manager = CompatibilityManager()
    response = client.post(
        "/api/sessions/offline",
        files={"file": ("call.wav", b"audio", "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["segments"][0]["translation"] == ""
    assert response.headers["Deprecation"] == "true"
```

- [ ] **Step 2: Run legacy tests and verify RED**

Run: `cd backend && python -m pytest tests/test_offline_api.py tests/test_url_api.py -q`

Expected: FAIL because endpoints still construct heavyweight providers directly.

- [ ] **Step 3: Route legacy requests through the job manager**

Create a job, await `manager.wait(job_id)`, read the persisted result, and return the existing `OfflineAnalysisResponse`. Add `Deprecation: true` and `Link: </api/jobs/upload>; rel="successor-version"`. Do not duplicate download or ASR logic.

- [ ] **Step 4: Keep realtime imports working without expanding scope**

Make `SessionService` accept provider dependencies with defaults so the existing realtime module imports and tests remain valid. Do not add new realtime UI or change its event contract in this task.

- [ ] **Step 5: Run backend API tests and commit**

Run: `cd backend && python -m pytest tests/test_offline_api.py tests/test_url_api.py tests/test_realtime_api.py -q`

Expected: PASS without model downloads.

```bash
git add backend/app/api/offline.py backend/app/api/url.py backend/app/sessions/service.py backend/tests/test_offline_api.py backend/tests/test_url_api.py
git commit -m "refactor: preserve legacy analysis endpoints through jobs"
```

### Task 12: Frontend Job Contracts and Polling Composable

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/composables/useAnalysisJob.ts`
- Test: `frontend/src/composables/useAnalysisJob.spec.ts`

- [ ] **Step 1: Write a failing polling state-machine test**

```typescript
import { vi } from "vitest";
import { useAnalysisJob } from "./useAnalysisJob";

it("polls lightweight status and fetches the result once", async () => {
  vi.useFakeTimers();
  const api = {
    createUrlJob: vi.fn().mockResolvedValue({ job_id: "job_1", status: "queued", progress: 0 }),
    getJobStatus: vi.fn()
      .mockResolvedValueOnce({ job_id: "job_1", status: "running", stage: "transcribing_sales", progress: 15 })
      .mockResolvedValueOnce({ job_id: "job_1", status: "completed", stage: "completed", progress: 100 }),
    getJobResult: vi.fn().mockResolvedValue({ session_id: "call_1", segments: [] })
  };
  const job = useAnalysisJob(api, 1000);
  await job.startUrl("https://example.com/call.wav");
  await vi.runAllTimersAsync();
  expect(api.getJobResult).toHaveBeenCalledTimes(1);
  expect(job.status.value).toBe("completed");
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd frontend && npm test -- --run src/composables/useAnalysisJob.spec.ts`

Expected: FAIL because composable and job API methods do not exist.

- [ ] **Step 3: Add exact TypeScript contracts and client methods**

Define `JobStatus`, `JobStage`, `SummaryStatus`, `JobCreateResponse`, `JobStatusResponse`, `AnalysisResult`, and the expanded emotion/summary fields. Add:

```typescript
export type JobStatus = "queued" | "running" | "completed" | "failed" | "interrupted";
export type JobStage =
  | "queued" | "preparing_audio" | "transcribing_sales"
  | "transcribing_customer" | "merging_segments" | "analyzing_emotion"
  | "scanning_risks" | "generating_summary" | "completed" | "failed";
export type SummaryStatus = "pending" | "completed" | "failed";

export interface JobCreateResponse {
  job_id: string;
  session_id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
}

export interface JobStatusResponse extends JobCreateResponse {
  summary_status: SummaryStatus;
  error_code?: string;
  error_message?: string;
}

export interface AnalysisResult {
  job_id: string;
  session_id: string;
  summary_status: SummaryStatus;
  summary_error_code?: string;
  segments: Segment[];
  quality: QualityScore;
  summary?: CallSummary;
}

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createUploadJob(file: File): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("file", file);
  return responseJson(await fetch(`${API_BASE}/api/jobs/upload`, { method: "POST", body: form }));
}

export async function createUrlJob(audioUrl: string): Promise<JobCreateResponse> {
  return responseJson(await fetch(`${API_BASE}/api/jobs/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_url: audioUrl })
  }));
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return responseJson(await fetch(`${API_BASE}/api/jobs/${jobId}`));
}

export async function getJobResult(jobId: string): Promise<AnalysisResult> {
  return responseJson(await fetch(`${API_BASE}/api/jobs/${jobId}/result`));
}

export async function retrySummary(jobId: string): Promise<JobStatusResponse> {
  return responseJson(await fetch(`${API_BASE}/api/jobs/${jobId}/retry-summary`, { method: "POST" }));
}

export function jobAudioUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/audio`;
}
```

- [ ] **Step 4: Implement bounded polling and cleanup**

Poll once per second while status is queued/running. Stop before fetching the result on failed/interrupted. Fetch the result once on completed. Clear timers on component unmount or when a new job starts. Keep summary failure separate from job failure.

Use an injectable API for deterministic tests:

```typescript
export interface AnalysisJobApi {
  createUploadJob(file: File): Promise<JobCreateResponse>;
  createUrlJob(url: string): Promise<JobCreateResponse>;
  getJobStatus(id: string): Promise<JobStatusResponse>;
  getJobResult(id: string): Promise<AnalysisResult>;
}

export function useAnalysisJob(api: AnalysisJobApi = client, intervalMs = 1000) {
  const jobId = ref<string>();
  const status = ref<JobStatus>();
  const stage = ref<JobStage>("queued");
  const progress = ref(0);
  const result = ref<AnalysisResult>();
  const error = ref<string>();
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function poll(): Promise<void> {
    if (!jobId.value) return;
    const state = await api.getJobStatus(jobId.value);
    status.value = state.status;
    stage.value = state.stage;
    progress.value = state.progress;
    if (state.status === "completed") {
      result.value = await api.getJobResult(jobId.value);
      return;
    }
    if (state.status === "failed" || state.status === "interrupted") {
      error.value = state.error_message || "任务处理失败";
      return;
    }
    timer = setTimeout(poll, intervalMs);
  }

  function dispose(): void {
    if (timer) clearTimeout(timer);
    timer = undefined;
  }

  async function accept(created: JobCreateResponse): Promise<void> {
    dispose();
    result.value = undefined;
    error.value = undefined;
    jobId.value = created.job_id;
    status.value = created.status;
    stage.value = created.stage;
    progress.value = created.progress;
    await poll();
  }

  async function startUrl(url: string): Promise<void> {
    await accept(await api.createUrlJob(url));
  }

  async function startUpload(file: File): Promise<void> {
    await accept(await api.createUploadJob(file));
  }

  onUnmounted(dispose);
  return { jobId, status, stage, progress, result, error, startUrl, startUpload, dispose };
}
```

- [ ] **Step 5: Run tests and commit**

Run: `cd frontend && npm test -- --run src/composables/useAnalysisJob.spec.ts`

Expected: PASS.

```bash
git add frontend/src/types.ts frontend/src/api/client.ts frontend/src/composables/useAnalysisJob.ts frontend/src/composables/useAnalysisJob.spec.ts
git commit -m "feat: add frontend analysis job state machine"
```

### Task 13: Toolbar, Progress, and Audio Player

**Files:**
- Modify: `frontend/src/components/Toolbar.vue`
- Create: `frontend/src/components/JobProgress.vue`
- Create: `frontend/src/components/AudioPlayer.vue`
- Test: `frontend/src/components/Toolbar.spec.ts`
- Test: `frontend/src/components/AudioPlayer.spec.ts`

- [ ] **Step 1: Write failing component tests**

```typescript
it("removes role and realtime controls", () => {
  const wrapper = mount(Toolbar, { props: { status: "准备就绪", audioUrl: "", isLoading: false } });
  expect(wrapper.find("select").exists()).toBe(false);
  expect(wrapper.text()).not.toContain("实时");
  expect(wrapper.find('input[aria-label="语音 URL"]').exists()).toBe(true);
});

it("seeks the audio element when seekTo is called", async () => {
  const wrapper = mount(AudioPlayer, { props: { src: "/api/jobs/job_1/audio" } });
  wrapper.vm.seekTo(12_300);
  expect(wrapper.find("audio").element.currentTime).toBe(12.3);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd frontend && npm test -- --run src/components/Toolbar.spec.ts src/components/AudioPlayer.spec.ts`

Expected: FAIL against current controls and missing player.

- [ ] **Step 3: Simplify the toolbar and add stable progress**

Toolbar props become `status`, `audioUrl`, and `isLoading`; emits become `updateAudioUrl`, `upload`, and `urlAnalyze`. Use Link and Upload icons. Give the long URL input `min-width: 18rem; width: min(42vw, 34rem)` and allow actions to wrap below 900px.

`JobProgress` maps known stages to Chinese labels and keeps a fixed 6px progress track plus one-line status area so progress changes do not shift layout.

- [ ] **Step 4: Implement the player contract**

Expose `seekTo(milliseconds)` via `defineExpose`, emit `timeUpdate` in milliseconds, and render the native `<audio controls preload="metadata">`. Handle 409/404 source errors with a compact Chinese state outside the audio element.

- [ ] **Step 5: Run tests and commit**

Run: `cd frontend && npm test -- --run src/components/Toolbar.spec.ts src/components/AudioPlayer.spec.ts`

Expected: PASS.

```bash
git add frontend/src/components/Toolbar.vue frontend/src/components/JobProgress.vue frontend/src/components/AudioPlayer.vue frontend/src/components/Toolbar.spec.ts frontend/src/components/AudioPlayer.spec.ts
git commit -m "feat: simplify analysis controls and add audio progress"
```

### Task 14: Transcript Modes, Filters, and Sensitive Highlighting

**Files:**
- Create: `frontend/src/utils/transcript.ts`
- Modify: `frontend/src/components/TranscriptPanel.vue`
- Test: `frontend/src/utils/transcript.spec.ts`
- Test: `frontend/src/components/TranscriptPanel.spec.ts`

- [ ] **Step 1: Write failing merge and rendering tests**

```typescript
import type { Segment, Speaker } from "../types";

function segment(speaker: Speaker, start_ms: number, end_ms: number, text: string): Segment {
  return {
    id: `${speaker}-${start_ms}`,
    session_id: "call_1",
    speaker,
    start_ms,
    end_ms,
    text,
    translation: "",
    emotion: { label: "neutral", confidence: 0.9, score: 0 },
    sensitive_hits: [],
    compliance_hits: [],
    confidence: 0.9,
    is_final: true
  };
}

it("merges only adjacent same-speaker segments within limits", () => {
  const merged = mergeTranscriptSegments([
    segment("sales", 0, 1000, "您好。"),
    segment("sales", 1800, 2400, "请问有什么需要？"),
    segment("customer", 2600, 3200, "我要退款。")
  ]);
  expect(merged).toHaveLength(2);
  expect(merged[0].text).toBe("您好。请问有什么需要？");
  expect(merged[1].speaker).toBe("customer");
});

it("renders four risk levels and emits seek", async () => {
  const segments = [segment("customer", 1200, 2500, "我要退款。")];
  segments[0].sensitive_hits = [{
    word: "退款", level: "critical", category: "售后", start: 2, end: 4,
    context: "我要退款。", speaker: "customer", segment_id: segments[0].id,
    start_ms: 1200, end_ms: 2500
  }];
  const wrapper = mount(TranscriptPanel, { props: { segments, currentTimeMs: 0 } });
  expect(wrapper.find(".hit-critical").attributes("aria-label")).toContain("严重风险");
  await wrapper.find("button.segment-time").trigger("click");
  expect(wrapper.emitted("seek")?.[0]).toEqual([segments[0].start_ms]);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd frontend && npm test -- --run src/utils/transcript.spec.ts src/components/TranscriptPanel.spec.ts`

Expected: FAIL because modes, filters, and accessible risk labels do not exist.

- [ ] **Step 3: Implement deterministic merged view**

Merge when speakers match, the gap is at most 1200 ms, and combined text is at most 120 characters. Keep `sourceSegmentIds`, first start, last end, and child segments. Never rewrite backend segment objects.

- [ ] **Step 4: Rebuild the transcript panel**

Add segmented controls for `逐句/合并` and `全部/仅销售/仅客户`. Show speaker, formatted time, emotion, and confidence. Use teal for sales and blue for customer plus role text. Highlight low/medium/high/critical with yellow/orange/red/deep red and an `aria-label` containing the Chinese level. Mark the segment active when `start_ms <= currentTimeMs < end_ms`.

- [ ] **Step 5: Run tests and commit**

Run: `cd frontend && npm test -- --run src/utils/transcript.spec.ts src/components/TranscriptPanel.spec.ts`

Expected: PASS.

```bash
git add frontend/src/utils/transcript.ts frontend/src/components/TranscriptPanel.vue frontend/src/utils/transcript.spec.ts frontend/src/components/TranscriptPanel.spec.ts
git commit -m "feat: add timestamped transcript views and risk highlights"
```

### Task 15: Summary, Risk, and Emotion Analysis Tabs

**Files:**
- Create: `frontend/src/utils/emotion.ts`
- Create: `frontend/src/components/AnalysisPanel.vue`
- Create: `frontend/src/components/SummaryPanel.vue`
- Create: `frontend/src/components/SensitivePanel.vue`
- Create: `frontend/src/components/EmotionChart.vue`
- Replace: `frontend/src/components/RiskPanel.vue`
- Test: `frontend/src/utils/emotion.spec.ts`
- Test: `frontend/src/components/AnalysisPanel.spec.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] **Step 1: Install ECharts and write failing data tests**

Run: `cd frontend && npm install echarts`

```typescript
import type { AnalysisResult, Segment, Speaker } from "../types";

function segment(speaker: Speaker, start_ms: number, end_ms: number, text: string): Segment {
  return {
    id: `${speaker}-${start_ms}`, session_id: "call_1", speaker,
    start_ms, end_ms, text, translation: "",
    emotion: { label: "neutral", confidence: 0.9, score: 0 },
    sensitive_hits: [], compliance_hits: [], confidence: 0.9, is_final: true
  };
}

const segments: Segment[] = [
  { ...segment("sales", 0, 1000, "您好。"), emotion: { label: "neutral", confidence: 0.9, score: 0 } },
  { ...segment("customer", 1200, 2500, "我要退款。"), emotion: { label: "angry", confidence: 0.8, score: -0.8 } },
  { ...segment("sales", 4000, 5000, "我来处理。"), emotion: { label: "positive", confidence: 0.7, score: 0.7 } }
];

const failedSummaryResult: AnalysisResult = {
  job_id: "job_1",
  session_id: "call_1",
  summary_status: "failed",
  summary_error_code: "summary_timeout",
  segments,
  quality: {
    score: 80, noise_level: "low", silence_ratio: 0.1,
    sales_talk_ratio: 0.6, customer_talk_ratio: 0.4,
    interruptions: 0, negative_emotion_ratio: 0.33,
    risk_hit_count: 1, suggestions: []
  }
};

it("builds separate chronological sales and customer series", () => {
  const result = buildEmotionSeries(segments);
  expect(result.sales.map(point => point.value[0])).toEqual([0, 4000]);
  expect(result.customer.map(point => point.value[0])).toEqual([1200]);
});

it("shows summary failure without hiding risk and emotion tabs", () => {
  const wrapper = mount(AnalysisPanel, { props: { result: failedSummaryResult } });
  expect(wrapper.text()).toContain("摘要生成失败");
  expect(wrapper.get('[role="tablist"]').text()).toContain("敏感词");
  expect(wrapper.get('[role="tablist"]').text()).toContain("情绪趋势");
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd frontend && npm test -- --run src/utils/emotion.spec.ts src/components/AnalysisPanel.spec.ts`

Expected: FAIL because analysis components do not exist.

- [ ] **Step 3: Implement summary and sensitive panels**

Summary shows overview first, then customer needs, sales promises, risk points, follow-up items, and next steps. On `summary_status=failed`, show a Retry icon button and emit `retrySummary`.

Sensitive panel groups hits in low/medium/high/critical order, displays counts with the same colors as transcript marks, and emits `seek(start_ms, segment_id)` when a row is clicked.

- [ ] **Step 4: Implement and safely dispose ECharts**

`buildEmotionSeries()` returns `[timeMs, score, segmentId]` points sorted by time. `EmotionChart` uses a stable-height `div`, initializes ECharts on mount, updates with `setOption(..., { notMerge: true })`, observes its container with `ResizeObserver`, and disposes both observer and chart on unmount. Add legend toggles for both speakers and a “仅客户” control. Chart clicks emit the segment time and ID.

- [ ] **Step 5: Run tests and commit**

Run: `cd frontend && npm test -- --run src/utils/emotion.spec.ts src/components/AnalysisPanel.spec.ts`

Expected: PASS.

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/utils/emotion.ts frontend/src/components/AnalysisPanel.vue frontend/src/components/SummaryPanel.vue frontend/src/components/SensitivePanel.vue frontend/src/components/EmotionChart.vue frontend/src/components/RiskPanel.vue frontend/src/utils/emotion.spec.ts frontend/src/components/AnalysisPanel.spec.ts
git commit -m "feat: add summary risk and emotion analysis tabs"
```

### Task 16: Integrate the Vue Workbench and Responsive Visual System

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.spec.ts`

- [ ] **Step 1: Write failing end-to-end component state tests**

```typescript
it("submits a URL job and renders completed analysis", async () => {
  const wrapper = mount(App, { global: { stubs: { EmotionChart: true } } });
  await wrapper.get('input[aria-label="语音 URL"]').setValue("https://example.com/call.wav");
  await wrapper.get('button[aria-label="识别 URL 录音"]').trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("通话内容");
  expect(wrapper.text()).toContain("客户要求退款");
});

it("seeks audio from transcript and analysis events", async () => {
  const wrapper = mount(App, { global: { stubs: { EmotionChart: true } } });
  await wrapper.findComponent(TranscriptPanel).vm.$emit("seek", 12_300);
  expect(wrapper.findComponent(AudioPlayer).vm.lastSeekMs).toBe(12_300);
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd frontend && npm test -- --run src/App.spec.ts`

Expected: FAIL because App still uses direct analysis responses and old components.

- [ ] **Step 3: Wire the new application state**

Use `useAnalysisJob()` as the only analysis workflow. On completed status, pass result segments to TranscriptPanel and AnalysisPanel, and set AudioPlayer source to `jobAudioUrl(jobId)`. Route every seek event through one `seekTo(ms)` method. Preserve completed local results while a summary retry is running.

- [ ] **Step 4: Replace visual styles with a Chinese operational workbench**

Use a white header, neutral `#f3f5f7` background, dark text, blue primary actions, teal sales, blue customer, and separate risk colors. Desktop layout is `grid-template-columns: minmax(0, 1fr) 360px`; the analysis panel is sticky below the header. Use 6px controls and no card nesting, gradients, decorative blobs, oversized type, or negative letter spacing. At `max-width: 900px`, switch to one column and make analysis tabs non-sticky. At `max-width: 600px`, stack URL input and actions at full width and ensure no horizontal overflow.

- [ ] **Step 5: Run tests, build, and commit**

Run:

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: all Vitest files pass and Vite production build succeeds.

```bash
git add frontend/src/App.vue frontend/src/styles.css frontend/src/App.spec.ts
git commit -m "feat: redesign the Chinese call analysis workbench"
```

### Task 17: Documentation, Integration Verification, and Browser QA

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Update dependency and environment documentation**

Document these variables with safe examples and no real secrets:

```dotenv
CALL_ASR_PREFERRED_DEVICE=cpu
CALL_ASR_JOB_RETENTION_DAYS=7
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_TIMEOUT_SECONDS=60
```

Remove documentation that describes `[en]` as translation. Document model download size expectations, background stages, the new Job API, dual-channel requirement, audio Range endpoint, and summary-only failure behavior.

- [ ] **Step 2: Run the complete backend suite**

Run: `cd backend && python -m pytest -q`

Expected: all tests pass without downloading or initializing real FunASR models. Model integrations must be behind injected fakes in routine tests.

- [ ] **Step 3: Run the complete frontend suite and production build**

Run:

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: all tests pass and build succeeds.

- [ ] **Step 4: Run one real-model smoke test and browser QA**

Start backend and frontend. Submit a short generated or approved dual-channel Chinese WAV. Verify the task advances through every stage, produces at least one sales and one customer segment with real timestamps, draws both emotion series, and either produces a DeepSeek summary or shows a summary-only missing-key error.

Use browser QA at 1440x900, 1024x768, and 390x844. Confirm URL controls, progress, player, transcript filters, 360px analysis rail, ECharts canvas, risk colors, and mobile stacking have no overlap or horizontal overflow. Save screenshots under a temporary QA directory, not the repository.

- [ ] **Step 5: Review repository state and commit docs**

Run:

```bash
git diff --check
git status --short
```

Confirm unrelated `backend/app/main.py`, `backend/ffmpeg.exe`, and `backend/ffprobe.exe` user changes remain untouched unless separately authorized.

```bash
git add .env.example README.md docs/API.md docs/ARCHITECTURE.md docs/DEPLOYMENT.md backend/pyproject.toml
git commit -m "docs: document background call analysis workflow"
```

---

## Final Verification Gate

- [ ] Run `cd backend && python -m pytest -q` and confirm zero failures.
- [ ] Run `cd frontend && npm test -- --run` and confirm zero failures.
- [ ] Run `cd frontend && npm run build` and confirm exit code 0.
- [ ] Run `git diff --check` and confirm no whitespace errors.
- [ ] Verify one real dual-channel recording produces interleaved, punctuated, timestamped dialogue.
- [ ] Verify summary failure does not erase local analysis.
- [ ] Verify URL SSRF cases are rejected before any request reaches a private address.
- [ ] Verify desktop and mobile screenshots show no overlap, clipped text, or blank emotion chart.
