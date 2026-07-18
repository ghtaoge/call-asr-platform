# Deployment Guide

## 主后端

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item ..\.env.example .env
python scripts\download_realtime_models.py
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

实时模型下载脚本会预取流式 Paraformer、FSMN-VAD 和 CAM++。离线 Paraformer、标点和 Emotion2Vec 在首次使用时由 ModelScope 缓存。

## 前端

```powershell
cd frontend
npm install
npm run build
```

开发环境：

```powershell
$env:VITE_API_BASE="http://127.0.0.1:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

生产环境使用 HTTPS 时，WebSocket 代理必须允许二进制帧并保持长连接。浏览器麦克风只在安全上下文或本机地址可用。

## CosyVoice 工作进程

要求：Git、Conda、Python 3.10 环境和足够的模型存储空间。安装脚本锁定官方提交 `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`，并下载两个模型：

- `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`：参考音频零样本声音复刻。
- `iic/CosyVoice-300M-SFT`：普通话、粤语、英语、日语和韩语默认音色。

```powershell
cd backend
.\scripts\setup_cosyvoice.ps1
```

生成一个随机令牌，并在工作进程和主后端中配置相同值：

```powershell
$env:COSYVOICE_WORKER_TOKEN="替换为随机令牌"
$env:CALL_ASR_COSYVOICE_WORKER_TOKEN=$env:COSYVOICE_WORKER_TOKEN
.\scripts\start_cosyvoice.ps1
```

主后端连接地址默认为 `http://127.0.0.1:18081`。工作进程只监听本机，且只允许读取 `backend/data/tts` 中的参考音频并写入该目录的任务输出。SFT 模型在第一次使用默认音色时延迟加载；首次合成会比后续任务慢。未启动工作进程时，其他功能保持可用，TTS 页面会显示“CosyVoice 工作进程不可用”。

Windows 开发机如果未启动工作进程，普通话和英语默认音色会自动调用系统 SAPI 生成 WAV；这只是可用性兜底，不支持自定义声音复刻，也不代表 CosyVoice 的音色质量。粤语、日语和韩语默认音色仍要求 CosyVoice 工作进程在线。

### Linux Docker Compose

正式环境建议使用仓库内的 Compose 编排。它包含 Redis 持久队列、CosyVoice GPU 工作进程和主后端，模型目录只读挂载，日志默认按 `20 MB x 5` 轮转。

```bash
cp deploy/.env.example deploy/.env
```

编辑 `deploy/.env`：

- `MODEL_ROOT` 指向已经离线准备好的模型根目录，必须包含 `Fun-CosyVoice3-0.5B` 和 `CosyVoice-300M-SFT`。
- `DATA_ROOT` 指向任务数据持久化目录。
- `TTS_GPU_DEVICE` 是分配给 CosyVoice 的宿主机 GPU 编号。
- `COSYVOICE_WORKER_TOKEN` 必须替换为足够长的随机令牌。

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml config --quiet
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

工作进程启动时加载两个模型，首次就绪可能需要数分钟。`/health/live` 只说明进程存活，`/health/ready` 只有模型加载成功后才返回成功。主后端使用 Redis Stream 保存队列状态；进程重启后，数据库中尚未完成的任务会重新入队，临时故障按配置的间隔自动重试。

## 环境变量

| 名称 | 默认值 | 说明 |
|---|---|---|
| `CALL_ASR_DATABASE_PATH` | `data/call_asr.sqlite3` | SQLite 路径 |
| `CALL_ASR_PREFERRED_DEVICE` | `auto` | `auto`、`cpu` 或 `cuda` |
| `CALL_ASR_MAX_AUDIO_BYTES` | `52428800` | 单个分析音频上限 |
| `CALL_ASR_JOB_RETENTION_DAYS` | `7` | 分析任务保留天数 |
| `DEEPSEEK_API_KEY` | 空 | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | 摘要模型名称 |
| `CALL_ASR_COSYVOICE_WORKER_URL` | `http://127.0.0.1:18081` | TTS 工作进程地址 |
| `CALL_ASR_COSYVOICE_WORKER_TOKEN` | 空 | 主后端调用令牌 |
| `CALL_ASR_TTS_HEALTH_CHECK_SECONDS` | `5` | TTS 工作进程健康检查间隔 |
| `CALL_ASR_TTS_WORKER_STARTUP_GRACE_SECONDS` | `300` | 工作进程启动宽限时间 |
| `CALL_ASR_REDIS_URL` | 空 | Redis Stream 地址；为空时使用进程内队列 |
| `CALL_ASR_TTS_RETRY_DELAYS_SECONDS` | `5,15,30,60,120` | 临时故障重试间隔 |
| `CALL_ASR_TTS_RETENTION_DAYS` | `7` | 临时音色与合成音频保留天数 |
| `CALL_ASR_TTS_MAX_REFERENCE_BYTES` | `20971520` | 参考音频上限 |
| `VITE_API_BASE` | `http://127.0.0.1:8000` | 前端访问的后端地址 |

## 上线检查

- 使用 HTTPS 和 WSS，并在反向代理中保留 `Range`、`Upgrade` 和 `Connection` 请求头。
- 为 API、WebSocket 和音频 URL 下载增加身份认证、租户隔离和审计日志。
- 将 DeepSeek Key、工作进程令牌放入密钥管理系统，不写入镜像或仓库。
- 为 SQLite 和 `backend/data` 设置备份、容量监控和定期清理。
- 根据 GPU 显存限制单机并发，并监控实时 ASR 延迟、任务失败率和 TTS 队列长度。
- 使用 `GET /api/tts/health` 监控 `status`、`queue_depth` 和 `error_code`，对连续不可用状态告警。
