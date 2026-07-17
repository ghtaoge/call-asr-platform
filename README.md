# Call ASR Platform

面向销售和客服通话质检的本地优先语音分析平台。系统使用阿里开源模型完成双声道语音识别、说话人区分、标点与分段，并提供声学情绪曲线、分级敏感词、合规检查、通话质检和 DeepSeek 结构化摘要。

## 主要能力

- SenseVoice + FSMN-VAD + CT-Punc：中文语音识别、时间戳、分句和标点
- 双声道角色区分：左声道为销售，右声道为客户
- Emotion2Vec：逐时间段声学情绪分析，分别显示销售和客户曲线
- 敏感词与合规规则：`low`、`medium`、`high`、`critical` 四级标记
- DeepSeek 摘要：概述、客户诉求、销售承诺、风险、待办和下一步建议
- 后台任务：上传或 URL 提交后异步处理，支持进度查询和失败恢复
- 原始录音回放：支持 HTTP Range，点击语句或图表节点可跳转时间点
- URL 安全下载：限制协议、重定向、文件大小，并阻止内网与本机地址

## 音频要求

角色区分依赖 Gooeto 双声道录音：第一声道为客户，第二声道为销售。单声道或多声道文件会返回 `unsupported_channel_layout`，不会猜测说话人身份。

支持 FFmpeg 能解码的 WAV、MP3、M4A、AAC、FLAC、OGG 等常见格式。单个文件默认不超过 50 MB。

## 启动后端

```powershell
cd call-asr-platform\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item ..\.env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在 `backend/.env` 中设置 `DEEPSEEK_API_KEY` 后才会生成智能摘要。没有 Key 时，本地识别、情绪、敏感词和质检仍会正常完成，摘要区会显示可重试状态。

SenseVoice 和 Emotion2Vec 在首次分析时按需加载，第一次运行会下载模型并耗时较长。`CALL_ASR_PREFERRED_DEVICE=auto` 会优先使用 CUDA，否则使用 CPU。

## 启动前端

```powershell
cd call-asr-platform\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

打开 `http://127.0.0.1:5173`。若后端不是 `8000` 端口，在启动前设置：

```powershell
$env:VITE_API_BASE="http://127.0.0.1:8022"
```

## 测试

```powershell
cd call-asr-platform\backend
python -m pytest -q
```

```powershell
cd call-asr-platform\frontend
npm test
npm run build
```

## API

- `POST /api/jobs/upload`：上传音频并创建任务
- `POST /api/jobs/url`：根据文本框中的语音 URL 创建任务
- `GET /api/jobs/{job_id}`：查询状态与进度
- `GET /api/jobs/{job_id}/result`：获取分析结果
- `GET /api/jobs/{job_id}/audio`：播放原始录音
- `POST /api/jobs/{job_id}/retry-summary`：重新生成 DeepSeek 摘要

旧的 `/api/sessions/offline` 和 `/api/sessions/url` 暂时保留为同步兼容接口，并返回 `Deprecation: true`。

## 数据与安全

任务音频保存在 `backend/data/jobs/`，默认保留 7 天。该目录、SQLite 数据库和 `.env` 都已加入 `.gitignore`。请勿把 DeepSeek API Key、客户录音或真实通话文本提交到 Git。

## 许可证

MIT
