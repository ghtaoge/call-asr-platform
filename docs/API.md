# API Reference

Default backend base URL:

```text
http://127.0.0.1:8000
```

## Health

```http
GET /api/health
```

Response:

```json
{
  "status": "ok",
  "app": "Call ASR Platform",
  "asr_provider": "mock",
  "device": "cpu",
  "sensitive_words_path": "data/sensitive_words.sample.json"
}
```

## Offline Analysis

```http
POST /api/sessions/offline
Content-Type: multipart/form-data
```

Form fields:

- `file`: audio file.

Response:

```json
{
  "session_id": "call_xxxxxxxx",
  "segments": [
    {
      "id": "call_xxxxxxxx_seg_001",
      "session_id": "call_xxxxxxxx",
      "speaker": "unknown",
      "start_ms": 0,
      "end_ms": 1000,
      "text": "您好我是顾问。",
      "translation": "[en] 您好我是顾问。",
      "language": "zh",
      "target_language": "en",
      "emotion": { "label": "neutral", "score": 0.62 },
      "sensitive_hits": [],
      "compliance_hits": [],
      "confidence": 0.92,
      "is_final": true
    }
  ],
  "quality": {
    "score": 92,
    "noise_level": "medium",
    "silence_ratio": 0.1,
    "sales_talk_ratio": 0,
    "customer_talk_ratio": 0,
    "interruptions": 0,
    "negative_emotion_ratio": 0,
    "risk_hit_count": 0,
    "suggestions": []
  },
  "summary": {
    "customer_needs": [],
    "sales_promises": [],
    "risk_points": [],
    "follow_up_items": [],
    "next_steps": ["复核通话摘要并安排下一步跟进"]
  }
}
```

## Realtime WebSocket

```text
WS /ws/realtime/{session_id}
```

### Client Events

Start:

```json
{
  "type": "start_session",
  "speaker": "sales",
  "target_language": "en"
}
```

Audio chunk:

```json
{
  "type": "audio_chunk",
  "speaker": "sales",
  "audio": "base64-encoded-audio-bytes"
}
```

End:

```json
{
  "type": "end_session"
}
```

### Server Events

```json
{ "type": "session_started", "session_id": "s1" }
```

```json
{ "type": "final_segment", "segment": {} }
```

```json
{ "type": "risk_alert", "hit": {} }
```

```json
{ "type": "quality_update", "quality": {} }
```

```json
{ "type": "summary_ready", "summary": {} }
```
