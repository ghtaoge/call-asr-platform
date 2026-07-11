# Call ASR Platform — 通话语音智能分析平台

本地优先的通话语音智能分析原型，面向销售/客服通话质检场景。系统支持离线录音上传、实时 WebSocket 音频流、敏感词识别、情绪标签、翻译字段、自动标点、长内容分段、风险告警、通话质量评分、话术合规检测和通话摘要。

## 功能特性

- 离线录音上传与分析
- 实时 WebSocket 通话流模拟
- 销售/客服说话人元数据区分
- Aho-Corasick 风格敏感词扫描，支持大词库
- 风险分级高亮：`low`、`medium`、`high`、`critical`
- 基于规则的话术合规检测
- 情绪标签与翻译 Provider 边界
- 通话质量评分与摘要生成
- 可选 `faster-whisper` Provider 边界，支持本地 ASR 模型
- CPU 优先可运行原型，预留 GPU 加速钩子

## 系统架构

```text
前端 React 工作台
  -> REST 上传 / WebSocket 实时流
后端 FastAPI
  -> 音频预处理边界
  -> ASR Provider
  -> 标点与分段
  -> 敏感词扫描
  -> 合规、情绪、翻译
  -> 质量评分与摘要
  -> SQLite 会话存储
```

详细文档：

- [架构设计](docs/ARCHITECTURE.md)
- [API 参考](docs/API.md)
- [部署指南](docs/DEPLOY.md)
- [敏感词词库](docs/SENSITIVE_WORDS.md)
- [开发指南](docs/DEVELOPMENT.md)

## 后端

```bash
cd call-asr-platform/backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .[test]
python -m pytest -v
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

默认 ASR Provider 为 `mock`，无需下载模型即可跑通完整产品流程。

可选本地模型依赖：

```bash
python -m pip install -e .[models]
```

`faster-whisper` Provider 已预留，后续可通过配置切换真实模型。CPU 环境默认可运行，检测到 CUDA 时可启用 GPU 加速配置。

## 前端

```bash
cd call-asr-platform/frontend
npm install
npm test
npm run dev
```

打开 `http://127.0.0.1:5173`。

如果端口 `8000` 或 `5173` 已被占用：

```powershell
cd call-asr-platform/backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8022
```

```powershell
cd call-asr-platform/frontend
$env:VITE_API_BASE="http://127.0.0.1:8022"
npm run dev -- --host 127.0.0.1 --port 5178
```

## 敏感词性能基准

```bash
cd call-asr-platform/backend
python scripts/bench_sensitive.py
```

压测脚本会构建 100,000 条敏感词并扫描样本文本，用于验证 Aho-Corasick 风格扫描器的基本性能。

## 第一版说明

- 敏感词按 `low`、`medium`、`high`、`critical` 分级，前端使用不同颜色高亮。
- 实时接口支持 `speaker=sales/customer/unknown`，可模拟电话系统按销售和客户区分音频流。
- 音频预处理目前是轻量 Provider 边界，已预留真实转码、VAD 和降噪接入点。
- 翻译、情绪和摘要第一版使用规则/占位 Provider，接口保持稳定，便于替换为本地开源模型。

## 许可证

MIT
