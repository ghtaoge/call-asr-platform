# Browser Realtime ASR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream browser microphone audio to the backend, show revisable partial text within one second, finalize timestamped sentences after pauses, cluster two speakers for manual sales/customer mapping, and launch post-call analysis without blocking the transcript.

**Architecture:** Replace the existing per-chunk offline WebSocket handler with a stateful realtime gateway. Browser `AudioWorklet` frames are normalized into a source-agnostic `AudioFrame`, deduplicated by sequence, and fed to a persistent FunASR streaming Paraformer/VAD session. Final segments use the transcript-first orchestrator from the preceding plan; a future Gooeto adapter can emit the same frames without changing ASR or UI contracts.

**Tech Stack:** FastAPI WebSocket, FunASR streaming Paraformer, FSMN-VAD, CAM++ speaker embeddings, NumPy, Vue 3, AudioWorklet, TypeScript, Vitest, pytest

---

## Prerequisite

Complete `docs/superpowers/plans/2026-07-17-transcript-first-async-analysis.md` first. This plan relies on independent transcript and analysis statuses plus partial result assembly.

## File Map

### Backend

- Create `backend/app/realtime/protocol.py`: binary frame codec and control/event models.
- Create `backend/app/realtime/source.py`: source adapter interface and browser PCM adapter.
- Create `backend/app/realtime/audio_sink.py`: bounded session audio recording for post-call analysis.
- Create `backend/app/realtime/streaming_asr.py`: provider protocol and FunASR implementation.
- Create `backend/app/realtime/speaker_clusterer.py`: two-speaker online clustering.
- Create `backend/app/realtime/session.py`: sequence, buffering, partial/final, pause, and reconnect state.
- Create `backend/app/realtime/manager.py`: active session lifecycle and post-call handoff.
- Modify `backend/app/api/realtime.py`: thin WebSocket transport adapter.
- Modify `backend/app/asr/model_registry.py`: lazy streaming ASR, VAD, and CAM++ loaders.
- Modify `backend/app/main.py`: create one realtime manager and close it during shutdown.
- Create `backend/tests/test_realtime_protocol.py`, `test_streaming_asr.py`, `test_realtime_session.py`, `test_realtime_manager.py`.
- Replace assertions in `backend/tests/test_realtime_api.py` with the versioned protocol.

### Frontend

- Create `frontend/public/pcm-worklet.js`: downsample and emit exact 20ms PCM16 chunks.
- Create `frontend/src/realtime/frame.ts`: encode the 16-byte binary frame header.
- Create `frontend/src/composables/useRealtimeSession.ts`: microphone, WebSocket, buffering, and events.
- Create `frontend/src/components/ModeSwitcher.vue`: analysis/realtime/TTS segmented control.
- Create `frontend/src/components/RealtimePanel.vue`: controls, level meter, transcript, and speaker mapping.
- Modify `frontend/src/App.vue`, `types.ts`, and `styles.css`.
- Create focused Vitest tests for the frame codec, composable, and panel.

## Task 1: Implement the Versioned Binary Audio Frame Protocol

**Files:**
- Create: `backend/app/realtime/__init__.py`
- Create: `backend/app/realtime/protocol.py`
- Create: `backend/app/realtime/source.py`
- Create: `backend/tests/test_realtime_protocol.py`

- [ ] **Step 1: Write failing frame codec tests**

```python
import struct
import pytest

from app.realtime.protocol import AudioFrame, FrameProtocolError, decode_audio_frame


def test_decodes_v1_pcm_frame():
    payload = b"\x01\x00\x02\x00"
    raw = struct.pack(">BBHIQ", 1, 0, 0, 7, 1_784_300_000_000) + payload
    frame = decode_audio_frame("s1", raw)
    assert frame == AudioFrame(
        session_id="s1",
        sequence=7,
        captured_at_ms=1_784_300_000_000,
        payload=payload,
    )


def test_rejects_wrong_version_and_large_payload():
    with pytest.raises(FrameProtocolError):
        decode_audio_frame("s1", struct.pack(">BBHIQ", 2, 0, 0, 1, 0))
    with pytest.raises(FrameProtocolError):
        decode_audio_frame("s1", struct.pack(">BBHIQ", 1, 0, 0, 1, 0) + b"x" * 4097)
```

- [ ] **Step 2: Run and verify failure**

```powershell
cd backend
python -m pytest tests/test_realtime_protocol.py -q
```

Expected: FAIL because `app.realtime.protocol` does not exist.

- [ ] **Step 3: Implement exact protocol parsing**

```python
from dataclasses import dataclass
import struct

HEADER = struct.Struct(">BBHIQ")
PROTOCOL_VERSION = 1
MAX_PAYLOAD_BYTES = 4096


class FrameProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class AudioFrame:
    session_id: str
    sequence: int
    captured_at_ms: int
    payload: bytes


def decode_audio_frame(session_id: str, raw: bytes) -> AudioFrame:
    if len(raw) < HEADER.size:
        raise FrameProtocolError("音频帧头不完整")
    version, flags, reserved, sequence, captured_at_ms = HEADER.unpack_from(raw)
    payload = raw[HEADER.size:]
    if version != PROTOCOL_VERSION or flags != 0 or reserved != 0:
        raise FrameProtocolError("不支持的实时音频协议")
    if not payload or len(payload) > MAX_PAYLOAD_BYTES or len(payload) % 2:
        raise FrameProtocolError("实时 PCM 载荷无效")
    return AudioFrame(session_id, sequence, captured_at_ms, payload)
```

Define Pydantic control messages for `start_session`, `pause_session`, `resume_session`, `map_speakers`, `end_session`, and `resume_session_connection`. Reject unknown control types with a stable `unsupported_event` error code.

Add the source boundary used by both browser and future Gooeto ingestion:

```python
class AudioSourceAdapter(Protocol):
    source: str

    def decode(self, session_id: str, payload: bytes) -> AudioFrame:
        raise NotImplementedError


class BrowserPcmAdapter:
    source = "browser_microphone"

    def decode(self, session_id: str, payload: bytes) -> AudioFrame:
        return decode_audio_frame(session_id, payload)
```

Register adapters by their exact `source` value. The WebSocket gateway selects `BrowserPcmAdapter` from the `start_session` message. A later Gooeto adapter must implement this protocol and may emit mono frames for clustering or stereo/channel-tagged normalized frames for direct role binding.

- [ ] **Step 4: Run protocol tests**

```powershell
python -m pytest tests/test_realtime_protocol.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/realtime backend/tests/test_realtime_protocol.py
git commit -m "feat: define realtime audio frame protocol"
```

## Task 2: Add a Persistent Streaming Paraformer Provider

**Files:**
- Create: `backend/app/realtime/streaming_asr.py`
- Modify: `backend/app/asr/model_registry.py`
- Create: `backend/tests/test_streaming_asr.py`

- [ ] **Step 1: Write failing provider tests with fake models**

```python
def test_streaming_provider_keeps_cache_between_chunks():
    model = FakeStreamingModel(["你", "你好"])
    provider = FunAsrStreamingProvider(model=model, vad=FakeVad(endpoint_on=2))
    session = provider.open_session()
    first = session.feed(PCM_600_MS, is_final=False)
    second = session.feed(PCM_600_MS, is_final=False)
    assert first.partial_text == "你"
    assert second.partial_text == "你好"
    assert second.endpoint is True
    assert model.cache_ids[0] == model.cache_ids[1]


def test_final_flush_resets_sentence_cache():
    session = provider.open_session()
    result = session.feed(PCM_200_MS, is_final=True)
    assert result.endpoint is True
    assert result.final_text
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_streaming_asr.py -q
```

Expected: FAIL because the streaming provider does not exist.

- [ ] **Step 3: Implement model loaders and provider session**

Add lazy registry loaders:

```python
def streaming_asr(self):
    return self._load(
        "streaming_asr",
        lambda: AutoModel(model="paraformer-zh-streaming", device=self.device),
    )


def streaming_vad(self):
    return self._load(
        "streaming_vad",
        lambda: AutoModel(model="fsmn-vad", device=self.device),
    )
```

The provider session owns separate ASR and VAD caches:

```python
class StreamingAsrSession:
    def __init__(self, model, vad) -> None:
        self.model = model
        self.vad = vad
        self.asr_cache: dict = {}
        self.vad_cache: dict = {}

    def feed(self, pcm16: bytes, is_final: bool) -> StreamingRecognition:
        samples = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        asr_result = self.model.generate(
            input=samples,
            cache=self.asr_cache,
            is_final=is_final,
            chunk_size=[0, 10, 5],
            encoder_chunk_look_back=4,
            decoder_chunk_look_back=1,
            disable_pbar=True,
        )
        vad_result = self.vad.generate(
            input=samples,
            cache=self.vad_cache,
            is_final=is_final,
            disable_pbar=True,
        )
        return normalize_streaming_result(asr_result, vad_result, is_final)
```

Keep model-specific parsing in `normalize_streaming_result()`. Tests must cover empty model output and punctuation cleanup without exposing FunASR tags.

- [ ] **Step 4: Run provider and registry tests**

```powershell
python -m pytest tests/test_streaming_asr.py tests/test_model_registry.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/realtime/streaming_asr.py backend/app/asr/model_registry.py backend/tests/test_streaming_asr.py backend/tests/test_model_registry.py
git commit -m "feat: add persistent streaming paraformer"
```

## Task 3: Build the Realtime Session State Machine

**Files:**
- Create: `backend/app/realtime/session.py`
- Create: `backend/app/realtime/audio_sink.py`
- Create: `backend/tests/test_realtime_session.py`

- [ ] **Step 1: Write failing state-machine tests**

```python
def test_partial_revision_increases_and_endpoint_finalizes_once(session):
    events = session.accept(frame(1, PCM_20_MS))
    events += session.accept(frame(2, PCM_20_MS))
    partials = [event for event in events if event.type == "partial_transcript"]
    assert [event.revision for event in partials] == sorted({event.revision for event in partials})

    events = session.accept_many(frames_until_endpoint())
    finals = [event for event in events if event.type == "final_transcript"]
    assert len(finals) == 1
    assert finals[0].segment.start_ms < finals[0].segment.end_ms


def test_duplicate_frame_is_acknowledged_but_not_transcribed(session):
    session.accept(frame(9, PCM_20_MS))
    events = session.accept(frame(9, PCM_20_MS))
    assert session.streaming_asr.feed_count == 1
    assert events[-1].type == "audio_ack"


def test_audio_sink_records_each_accepted_frame_once(tmp_path):
    sink = RealtimeAudioSink(tmp_path / "session.wav")
    sink.append(frame(1, PCM_20_MS))
    sink.append(frame(2, PCM_20_MS))
    path = sink.close()
    with wave.open(str(path), "rb") as recorded:
        assert recorded.getframerate() == 16000
        assert recorded.getnchannels() == 1
        assert recorded.getnframes() == 640
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_realtime_session.py -q
```

Expected: FAIL because no state machine exists.

- [ ] **Step 3: Implement bounded buffering and event production**

`RealtimeSession.accept()` must:

1. Reject sequence gaps larger than the 10-second frame window.
2. Ignore already acknowledged sequences.
3. Append exactly 20ms of PCM to a sentence buffer.
4. Feed ASR/VAD every 30 frames (600ms), or immediately on final flush.
5. Emit `partial_transcript` only when normalized text changes.
6. Emit one `final_transcript` on endpoint, persist a stable segment ID, then reset only sentence caches.
7. Emit `audio_ack` with the largest contiguous sequence.

Append each newly accepted frame to `RealtimeAudioSink` before acknowledging it. The sink writes mono PCM16 into one WAV file using the standard `wave` module, ignores duplicate sequences at the session layer, stays open across a recoverable disconnect, and closes exactly once on session end or terminal failure. Its returned path is the audio input for post-call emotion and quality analysis.

Use a single monotonic revision counter:

```python
def _partial_event(self, text: str) -> PartialTranscriptEvent | None:
    if not text or text == self.partial_text:
        return None
    self.partial_text = text
    self.revision += 1
    return PartialTranscriptEvent(revision=self.revision, text=text)
```

Pause accepts no binary frames. Resume preserves ASR context. A final flush at `end_session` must finalize remaining speech once.

- [ ] **Step 4: Run state tests**

```powershell
python -m pytest tests/test_realtime_session.py -q
```

Expected: PASS, including bounded buffer and duplicate-frame cases.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/realtime/session.py backend/app/realtime/audio_sink.py backend/tests/test_realtime_session.py
git commit -m "feat: manage realtime transcript sessions"
```

## Task 4: Add Two-Speaker Clustering and Business Role Mapping

**Files:**
- Create: `backend/app/realtime/speaker_clusterer.py`
- Modify: `backend/app/asr/model_registry.py`
- Modify: `backend/app/realtime/session.py`
- Modify: `backend/app/sessions/repository.py`
- Create: `backend/tests/test_speaker_clusterer.py`

- [ ] **Step 1: Write failing clustering tests**

```python
def test_assigns_at_most_two_stable_clusters():
    clusterer = TwoSpeakerClusterer(FakeEmbeddingModel([A, A_NEAR, B, B_NEAR]))
    assert clusterer.assign(WAV_A) == "speaker_1"
    assert clusterer.assign(WAV_A2) == "speaker_1"
    assert clusterer.assign(WAV_B) == "speaker_2"
    assert clusterer.assign(WAV_B2) == "speaker_2"


async def test_mapping_updates_existing_segments(repository):
    await repository.save_segments("s1", provisional_segments)
    await repository.save_speaker_mapping(
        "s1", {"speaker_1": "sales", "speaker_2": "customer"}
    )
    segments = await repository.list_segments("s1")
    assert [segment.speaker.value for segment in segments] == ["sales", "customer"]
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_speaker_clusterer.py -q
```

Expected: FAIL because clustering and mapping persistence do not exist.

- [ ] **Step 3: Implement CAM++ embeddings and two-centroid assignment**

Add the registry model:

```python
def speaker_embedding(self):
    return self._load(
        "speaker_embedding",
        lambda: AutoModel(model="cam++", device=self.device),
    )
```

Normalize embeddings to unit length. The first valid utterance creates `speaker_1`. An utterance whose cosine similarity to speaker 1 is below `0.72` creates `speaker_2`. Once both exist, assign the nearest centroid and update that centroid with an exponential moving average of `0.2`. Utterances shorter than 800ms return `unknown` and do not update centroids.

Store provisional cluster IDs separately from the business `Speaker` enum until the user maps them. Mapping updates base segments transactionally and marks role-dependent risk, quality, and summary artifacts stale for rescheduling; it never reruns ASR.

- [ ] **Step 4: Run clustering and repository tests**

```powershell
python -m pytest tests/test_speaker_clusterer.py tests/test_session_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/realtime/speaker_clusterer.py backend/app/asr/model_registry.py backend/app/realtime/session.py backend/app/sessions/repository.py backend/tests/test_speaker_clusterer.py backend/tests/test_session_repository.py
git commit -m "feat: cluster and map realtime speakers"
```

## Task 5: Replace the WebSocket Prototype With a Reconnectable Manager

**Files:**
- Create: `backend/app/realtime/manager.py`
- Modify: `backend/app/api/realtime.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_realtime_api.py`
- Create: `backend/tests/test_realtime_manager.py`

- [ ] **Step 1: Write failing WebSocket and reconnect tests**

```python
def test_websocket_emits_partial_final_and_ack(client):
    with client.websocket_connect("/ws/realtime/s1") as ws:
        ws.send_json(START_MESSAGE)
        assert ws.receive_json()["type"] == "session_started"
        ws.send_bytes(encode_frame(1, PCM_20_MS))
        messages = receive_until(ws, "audio_ack")
        assert messages[-1]["sequence"] == 1


async def test_reconnect_replays_only_unacknowledged_frames(manager):
    session = await manager.start("s1", START_MESSAGE)
    await manager.accept_frame("s1", frame(1))
    await manager.disconnect("s1")
    resumed = await manager.resume("s1", last_server_ack=1)
    assert resumed.next_sequence == 2
```

- [ ] **Step 2: Run and verify failure**

```powershell
python -m pytest tests/test_realtime_api.py tests/test_realtime_manager.py -q
```

Expected: FAIL against the old Base64 JSON chunk handler.

- [ ] **Step 3: Implement a thin route and shared manager**

The route only dispatches JSON or bytes:

```python
@router.websocket("/ws/realtime/{session_id}")
async def realtime_session(websocket: WebSocket, session_id: str) -> None:
    manager: RealtimeManager = websocket.app.state.realtime_manager
    await websocket.accept()
    connection = await manager.connect(session_id)
    try:
        while True:
            message = await websocket.receive()
            events = await connection.handle(message)
            for event in events:
                await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        await connection.disconnect()
```

`RealtimeManager` retains disconnected sessions for 30 seconds, caps each unprocessed buffer at 10 seconds, limits a session to 2 hours, and runs cleanup from one background task. Do not create a repository or model per WebSocket connection.

- [ ] **Step 4: Run realtime backend tests**

```powershell
python -m pytest tests/test_realtime_api.py tests/test_realtime_manager.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/realtime/manager.py backend/app/api/realtime.py backend/app/main.py backend/tests/test_realtime_api.py backend/tests/test_realtime_manager.py
git commit -m "feat: add reconnectable realtime gateway"
```

## Task 6: Capture 20ms PCM Frames in the Browser

**Files:**
- Create: `frontend/public/pcm-worklet.js`
- Create: `frontend/src/realtime/frame.ts`
- Create: `frontend/src/realtime/frame.spec.ts`
- Create: `frontend/src/composables/useRealtimeSession.ts`
- Create: `frontend/src/composables/useRealtimeSession.spec.ts`

- [ ] **Step 1: Write failing frame and composable tests**

```typescript
it("encodes the version, sequence, timestamp and little-endian PCM payload", () => {
  const frame = encodeAudioFrame(7, 1784300000000n, new Int16Array([1, 2]));
  const view = new DataView(frame);
  expect(view.getUint8(0)).toBe(1);
  expect(view.getUint32(4, false)).toBe(7);
  expect(view.getBigUint64(8, false)).toBe(1784300000000n);
  expect(view.getInt16(16, true)).toBe(1);
});


it("replaces a partial and appends one final segment", async () => {
  const state = useRealtimeSession(fakeDependencies);
  fakeSocket.message({ type: "partial_transcript", revision: 1, text: "你" });
  fakeSocket.message({ type: "partial_transcript", revision: 2, text: "你好" });
  fakeSocket.message({ type: "final_transcript", segment: FINAL_SEGMENT });
  expect(state.partialText.value).toBe("");
  expect(state.segments.value).toEqual([FINAL_SEGMENT]);
});
```

- [ ] **Step 2: Run and verify failure**

```powershell
cd frontend
npm test -- --run src/realtime/frame.spec.ts src/composables/useRealtimeSession.spec.ts
```

Expected: FAIL because no realtime frontend modules exist.

- [ ] **Step 3: Implement AudioWorklet, frame encoding, and composable**

`pcm-worklet.js` must buffer resampled samples until exactly 320 samples are available:

```javascript
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = [];
    this.ratio = sampleRate / 16000;
    this.cursor = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    while (this.cursor < input.length) {
      const value = input[Math.floor(this.cursor)];
      this.pending.push(Math.max(-1, Math.min(1, value)));
      this.cursor += this.ratio;
    }
    this.cursor -= input.length;
    while (this.pending.length >= 320) {
      const pcm = new Int16Array(320);
      for (let i = 0; i < 320; i += 1) pcm[i] = Math.round(this.pending.shift() * 32767);
      this.port.postMessage(pcm, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor("pcm-worklet", PcmWorklet);
```

The composable requests `getUserMedia({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true, autoGainControl: false } })`, creates the worklet, maintains sequence/ack state, buffers the last 500 frames, and reconnects for up to 30 seconds. Echo cancellation stays off because this mode intentionally captures both the local speaker and the remote party played through the room speaker. Stop every media track on end or unmount.

- [ ] **Step 4: Run frontend realtime unit tests**

```powershell
npm test -- --run src/realtime/frame.spec.ts src/composables/useRealtimeSession.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/public/pcm-worklet.js frontend/src/realtime frontend/src/composables/useRealtimeSession.ts frontend/src/composables/useRealtimeSession.spec.ts
git commit -m "feat: stream browser microphone audio"
```

## Task 7: Add Realtime Mode and Transcript UI

**Files:**
- Create: `frontend/src/components/ModeSwitcher.vue`
- Create: `frontend/src/components/RealtimePanel.vue`
- Create: `frontend/src/components/RealtimePanel.spec.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.spec.ts`

- [ ] **Step 1: Write failing interaction tests**

```typescript
it("shows partial text separately and keeps finalized sentences", async () => {
  const wrapper = mount(RealtimePanel, { props: realtimeProps });
  expect(wrapper.get("[data-partial]").text()).toBe("正在确认：您好");
  expect(wrapper.findAll(".segmentRow")).toHaveLength(2);
});


it("maps both provisional speakers", async () => {
  const wrapper = mount(RealtimePanel, { props: realtimeProps });
  await wrapper.get("select[data-speaker='speaker_1']").setValue("sales");
  await wrapper.get("select[data-speaker='speaker_2']").setValue("customer");
  expect(wrapper.emitted("map-speakers")?.[0]).toEqual([
    { speaker_1: "sales", speaker_2: "customer" }
  ]);
});
```

- [ ] **Step 2: Run and verify failure**

```powershell
npm test -- --run src/components/RealtimePanel.spec.ts src/App.spec.ts
```

Expected: FAIL because no realtime mode exists.

- [ ] **Step 3: Implement the work-focused realtime view**

Use a segmented mode switch with `录音分析`, `实时识别`, and a disabled-until-plan-3 `语音合成` target. The realtime toolbar uses familiar microphone, pause, resume, and stop icons with tooltips. Keep button dimensions stable.

Render final segments with the existing `TranscriptPanel`. Render one subdued `data-partial` row below it. Add connection state, duration, and a fixed-height level meter. Auto-follow only while the user is within 80px of the bottom; otherwise show an icon button labeled by tooltip `回到最新内容`.

Speaker mapping uses two compact selects. Disable choosing the same business role twice. Emit one complete mapping only when both values are valid.

- [ ] **Step 4: Run UI tests and production build**

```powershell
npm test -- --run src/components/RealtimePanel.spec.ts src/App.spec.ts
npm run build
```

Expected: PASS and build succeeds.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/ModeSwitcher.vue frontend/src/components/RealtimePanel.vue frontend/src/components/RealtimePanel.spec.ts frontend/src/App.vue frontend/src/types.ts frontend/src/styles.css frontend/src/App.spec.ts
git commit -m "feat: add realtime recognition workspace"
```

## Task 8: Handoff Ended Calls to Post-Call Analysis

**Files:**
- Modify: `backend/app/realtime/manager.py`
- Modify: `backend/app/jobs/manager.py`
- Modify: `backend/app/sessions/repository.py`
- Modify: `frontend/src/composables/useRealtimeSession.ts`
- Modify: `frontend/src/App.vue`
- Test: `backend/tests/test_realtime_manager.py`
- Test: `frontend/src/App.spec.ts`

- [ ] **Step 1: Write failing handoff tests**

```python
async def test_end_session_preserves_transcript_and_starts_post_analysis(manager):
    session = await manager.start("s1", START_MESSAGE)
    session.final_segments = [SEGMENT_1, SEGMENT_2]
    events = await manager.end("s1")
    assert any(event.type == "session_ended" for event in events)
    status = await manager.jobs.get_status(session.job_id)
    assert status.transcript_status == ModuleStatus.completed
    assert status.emotion_status in {ModuleStatus.pending, ModuleStatus.running}
```

- [ ] **Step 2: Run and verify failure**

```powershell
cd backend
python -m pytest tests/test_realtime_manager.py -q
```

Expected: FAIL because realtime sessions do not use the job orchestrator.

- [ ] **Step 3: Implement transcript-only handoff**

Add a `JobManager.create_realtime_analysis(session_id, segments, audio_path)` entry point. It marks transcript complete without running offline ASR, then schedules risk, emotion, quality, and summary using the same module methods as uploaded jobs.

During the live call, each final segment runs lightweight risk scanning and emits `risk_update`. On end, the persisted call audio and segments become the stable post-call input. The frontend switches from WebSocket event state to ordinary job polling after `session_ended` provides `job_id`.

- [ ] **Step 4: Run all realtime and partial-analysis tests**

```powershell
python -m pytest tests/test_realtime_api.py tests/test_realtime_manager.py tests/test_job_manager.py -q
cd ../frontend
npm test -- --run src/composables/useRealtimeSession.spec.ts src/components/RealtimePanel.spec.ts src/App.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/realtime/manager.py backend/app/jobs/manager.py backend/app/sessions/repository.py backend/tests/test_realtime_manager.py frontend/src/composables/useRealtimeSession.ts frontend/src/App.vue frontend/src/App.spec.ts
git commit -m "feat: analyze completed realtime calls"
```

## Task 9: Full Verification and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT.md`

- [ ] **Step 1: Run complete automated checks**

```powershell
cd backend
python -m pytest -q
cd ../frontend
npm test -- --run
npm run build
```

Expected: all tests PASS and build succeeds.

- [ ] **Step 2: Measure realtime latency with a deterministic fixture**

Feed a timestamped PCM fixture at realtime speed and record event times. Assert the warmed model emits at least one partial within 1 second of speech data arriving and finalizes within 2 seconds after the fixture's endpoint silence. Save the benchmark command in `docs/DEVELOPMENT.md`.

- [ ] **Step 3: Browser QA**

Verify microphone permission denial, start, pause, resume, stop, partial replacement, speaker mapping, manual upward scroll, return-to-latest, disconnect recovery, and post-call analysis on desktop and mobile widths. Confirm zero console errors.

- [ ] **Step 4: Document protocol and Gooeto adapter boundary**

Document the 16-byte frame header, control/events, limits, reconnect window, and `AudioFrame` fields. State explicitly that Gooeto production ingestion is not implemented yet and must only supply normalized frames through `AudioSourceAdapter`.

- [ ] **Step 5: Commit**

```powershell
git add README.md docs/API.md docs/ARCHITECTURE.md docs/DEVELOPMENT.md
git commit -m "docs: explain realtime recognition protocol"
```

## Completion Criteria

- Browser microphone audio reaches one persistent streaming ASR session.
- Partial text updates within the selected one-second target on a warmed CPU service.
- A pause endpoint creates one timestamped final segment without duplicate text.
- Duplicate and replayed frames are idempotent; 30-second reconnect preserves the session.
- Two speaker clusters can be mapped to sales/customer and historical segments update.
- Ending the call preserves transcript and starts independent post-call modules.
- Realtime ASR does not recreate repositories or models per audio frame.
- Backend tests, frontend tests, latency fixture, browser QA, and production build pass.
