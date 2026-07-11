# Architecture

Call ASR Platform is split into a FastAPI backend and a React workbench frontend.

## Backend Modules

```text
app/api            HTTP and WebSocket routes
app/audio          audio preprocessing boundary
app/asr            ASR provider protocol and implementations
app/postprocess    punctuation, cleanup, and segmentation
app/sensitive      sensitive-word automaton and lexicon store
app/compliance     rule-based script compliance checks
app/emotion        text emotion provider
app/translation    translation provider boundary
app/quality        call quality scoring
app/summary        summary generation
app/sessions       SQLite persistence and orchestration
```

The first runnable version uses deterministic providers for ASR, translation, emotion, and summary so the product flow can run without downloading large models. Real model integrations should be added behind existing provider boundaries.

## Analysis Pipeline

1. Receive audio from offline upload or realtime WebSocket.
2. Normalize audio through `AudioPreprocessor`.
3. Transcribe with the configured ASR provider.
4. Add punctuation and normalize text.
5. Scan text with the sensitive-word automaton.
6. Run compliance, emotion, and translation providers.
7. Calculate quality score.
8. Generate call summary and follow-up suggestions.
9. Store segments and artifacts in SQLite.
10. Return REST response or push WebSocket events.

## Realtime Flow

Realtime mode uses `WS /ws/realtime/{session_id}`. Clients send `start_session`, `audio_chunk`, and `end_session`. The backend emits `session_started`, `final_segment`, `risk_alert`, `quality_update`, and `summary_ready`.

The current realtime implementation reuses the offline analysis service per chunk. This is intentionally simple and stable for the prototype. A later version can add rolling-window ASR state and partial transcript stabilization.

## Provider Strategy

Provider boundaries keep the first version useful without hard-coding one model stack:

- ASR: mock provider now, optional `faster-whisper` provider prepared.
- Audio preprocessing: lightweight boundary now, future `ffmpeg`, VAD, and denoise providers.
- Translation: deterministic provider now, future local translation model.
- Emotion: rule provider now, future text/audio classifier.
- Summary: rule generator now, future local LLM.

## Storage

SQLite stores sessions, segments, quality scores, and summaries. Uploaded audio storage is intentionally minimal in v1. For production, add object storage and a task queue before handling high-volume recordings.
