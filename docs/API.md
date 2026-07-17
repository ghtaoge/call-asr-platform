# API Reference

默认后端地址为 `http://127.0.0.1:8000`。

## 健康检查

```http
GET /api/health
```

## 离线分析任务

上传文件：

```http
POST /api/jobs/upload
Content-Type: multipart/form-data
```

表单字段为 `file`。根据音频 URL 创建任务：

```http
POST /api/jobs/url
Content-Type: application/json

{"audio_url":"https://example.com/call.wav"}
```

两个接口均返回 `202 Accepted`：

```json
{
  "job_id": "job_xxxxxxxx",
  "session_id": "call_xxxxxxxx",
  "status": "queued",
  "stage": "queued",
  "progress": 0
}
```

查询任务：

```http
GET /api/jobs/{job_id}
```

响应除整体 `status`、`stage`、`progress` 外，还包含 `transcript_status`、`emotion_status`、`risk_status`、`quality_status`、`summary_status` 和 `module_errors`。模块状态为 `pending`、`running`、`completed` 或 `failed`。

只要 `transcript_status=completed` 即可读取结果，不需要等待所有分析完成：

```http
GET /api/jobs/{job_id}/result
```

结果包含带 `start_ms`、`end_ms`、`speaker`、标点和风险命中的 `segments`。尚未完成的 `quality` 或 `summary` 为 `null`，前端应继续轮询任务状态。

重试单个后处理模块：

```http
POST /api/jobs/{job_id}/retry/{module}
```

`module` 可取 `emotion`、`risk`、`quality` 或 `summary`。兼容接口 `POST /api/jobs/{job_id}/retry-summary` 仍保留。

播放原始录音：

```http
GET /api/jobs/{job_id}/audio
Range: bytes=0-1048575
```

服务支持 HTTP Range，并返回 `206 Partial Content`。

## 实时 WebSocket

```text
WS /ws/realtime/{session_id}
```

连接后先发送控制消息：

```json
{
  "type": "start_session",
  "codec": "pcm_s16le",
  "sample_rate": 16000,
  "channels": 1,
  "source": "browser_microphone"
}
```

音频使用二进制帧，固定 16 字节大端序帧头：

| 字段 | 类型 | 长度 | 说明 |
|---|---|---:|---|
| version | uint8 | 1 | 当前为 `1` |
| flags | uint8 | 1 | 当前为 `0` |
| reserved | uint16 | 2 | 当前为 `0` |
| sequence | uint32 | 4 | 单调递增帧序号 |
| captured_at_ms | uint64 | 8 | 客户端采集时间 |
| payload | PCM S16LE | 640 | 20 ms、16 kHz、单声道 |

主要服务端事件：

```json
{"type":"session_started","session_id":"...","sequence":-1,"resumed":false}
{"type":"audio_ack","sequence":10}
{"type":"partial_transcript","text":"临时识别文字"}
{"type":"final_transcript","segment":{"start_ms":0,"end_ms":1680,"text":"最终语句。"}}
{"type":"risk_update","segment_id":"...","sensitive_hits":[],"compliance_hits":[]}
{"type":"session_ended","job_id":"job_xxxxxxxx"}
```

控制消息：

```json
{"type":"pause_session"}
{"type":"resume_session"}
{"type":"map_speakers","mapping":{"speaker_1":"sales","speaker_2":"customer"}}
{"type":"resume_session_connection","last_ack":10}
{"type":"end_session"}
```

结束事件返回的 `job_id` 可直接交给离线任务查询接口，继续获取情绪、风险、质检和摘要。

## TTS

上传参考音频并自动识别参考文本：

```http
POST /api/tts/voices/clone
Content-Type: multipart/form-data
```

表单字段为 `file` 和 `consent=true`。音频时长必须为 3 到 30 秒。响应：

```json
{
  "voice_id": "voice_xxxxxxxx",
  "prompt_text": "参考音频识别文本。",
  "expires_at": "2026-07-24T12:00:00Z"
}
```

创建合成任务：

```http
POST /api/tts/jobs
Content-Type: application/json

{"voice_id":"voice_xxxxxxxx","text":"需要合成的中文内容。"}
```

查询状态和获取音频：

```http
GET /api/tts/jobs/{job_id}
GET /api/tts/jobs/{job_id}/audio
GET /api/tts/jobs/{job_id}/audio?download=true
```

状态为 `queued`、`running`、`completed`、`failed` 或 `expired`。失败时返回 `error_code` 和可直接展示的中文 `error_message`。音频响应支持 Range，并带有 `X-Audio-Origin: ai-generated` 标记。

## 兼容接口

`POST /api/sessions/offline` 和 `POST /api/sessions/url` 作为旧版同步接口暂时保留，并返回 `Deprecation: true` 响应头。新客户端应使用 `/api/jobs/*`。
