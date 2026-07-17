# Call ASR Platform

面向销售和客服通话质检的本地优先语音分析平台。系统使用阿里开源 FunASR/ModelScope 模型完成离线和实时中文语音识别、标点分句、说话人区分及声学情绪识别，并提供敏感词、合规质检、DeepSeek 通话摘要和 CosyVoice 声音复刻。

## 主要能力

- 离线分析：上传文件或填写音频 URL，先返回带时间戳的逐句通话内容，再异步计算情绪、风险、质检和摘要。
- 实时识别：浏览器麦克风以 20 ms PCM 帧传输，实时展示临时文字、最终分句、时间点和风险标记。
- 角色区分：Gooeto 双声道录音固定为第一/左声道客户、第二/右声道销售；实时单声道使用 CAM++ 聚类后由用户映射角色。
- 播放联动：拖动音频进度条自动定位并滚动到最近的识别语句，录音结尾仍保留最后一句。
- 独立分析模块：Emotion2Vec 情绪曲线、分级敏感词、合规规则、通话质检和 DeepSeek 摘要互不阻塞，失败模块可单独重试。
- 语音合成：上传 3 到 30 秒参考音频并确认授权，使用独立 CosyVoice 工作进程合成、播放和下载音频。

## 启动后端

```powershell
cd call-asr-platform\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item ..\.env.example .env
python scripts\download_realtime_models.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

首次使用模型时会下载较大文件。`CALL_ASR_PREFERRED_DEVICE=auto` 优先使用 CUDA，否则使用 CPU。`backend/.env` 中配置 `DEEPSEEK_API_KEY` 后才会生成智能摘要；未配置不会影响转写和其他分析模块。

## 启动前端

```powershell
cd call-asr-platform\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

打开 `http://127.0.0.1:5173`。浏览器麦克风要求安全上下文，`localhost` 和 `127.0.0.1` 可直接使用。

## 启动 CosyVoice

CosyVoice 使用独立 Python 3.10 Conda 环境，避免其依赖与主后端冲突。机器需要先安装 Git、Conda 和可用的模型运行环境。

```powershell
cd call-asr-platform\backend
.\scripts\setup_cosyvoice.ps1
$env:COSYVOICE_WORKER_TOKEN="请设置随机令牌"
$env:CALL_ASR_COSYVOICE_WORKER_TOKEN=$env:COSYVOICE_WORKER_TOKEN
.\scripts\start_cosyvoice.ps1
```

工作进程默认监听 `127.0.0.1:18081`。令牌必须与主后端 `.env` 中的 `CALL_ASR_COSYVOICE_WORKER_TOKEN` 一致。详细步骤见 [部署文档](docs/DEPLOYMENT.md)。

## 测试

```powershell
cd call-asr-platform\backend
python -m pytest -q

cd ..\frontend
npm test -- --run
npm run build
```

## 数据与安全

任务音频、实时录音、临时音色和合成音频默认保留 7 天，保存在 `backend/data/`，不会提交到 Git。请勿提交 `.env`、DeepSeek API Key、客户录音或真实通话文本。TTS 音色只用于用户明确授权的声音。

## 文档

- [API 参考](docs/API.md)
- [系统架构](docs/ARCHITECTURE.md)
- [部署说明](docs/DEPLOYMENT.md)

## 许可证

MIT
