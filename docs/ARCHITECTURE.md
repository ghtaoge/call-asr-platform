# Architecture

项目由 FastAPI 后端、Vue 3 工作台和隔离的 CosyVoice 工作进程组成。主后端负责业务编排和数据持久化；推理工作通过线程执行器运行，避免阻塞事件循环。

## 后端模块

```text
app/api          REST 与 WebSocket 路由
app/audio        解码、双声道拆分、WAV 标准化和 Range 响应
app/asr          Paraformer/SenseVoice 模型与生命周期管理
app/realtime     流式 ASR、VAD、CAM++ 聚类、协议和会话状态
app/emotion      Emotion2Vec 声学情绪识别
app/sensitive    敏感词自动机与词库
app/compliance   话术合规规则
app/summary      本地兜底摘要和 DeepSeek 结构化摘要
app/jobs         异步任务、模块状态、重试和保留策略
app/sessions     会话、语句及分析产物持久化
app/tts          音色、TTS 队列、存储和工作进程客户端
```

## 转写优先流程

1. 接收上传文件、音频 URL 或实时会话生成的 WAV。
2. 标准化并校验音频；离线双声道按 Gooeto 协议拆分客户和销售声道。
3. Paraformer 完成 VAD、时间戳、标点和分句。
4. 立即保存语句并将 `transcript_status` 设为 `completed`，前端开始展示通话内容。
5. 情绪、风险和摘要独立执行并分别更新模块状态；质检在相关数据可用后执行。
6. 单个后处理模块失败不会清空转写，也不会阻塞其他模块；用户可单独重试。

会话表保存稳定的转写结果，情绪和风险以独立产物保存，读取结果时再合并到语句中。这样重试某一模块不会覆盖其他模块的数据。

## 实时识别流程

浏览器的 AudioWorklet 将麦克风音频重采样为 16 kHz、单声道、16 位 PCM，每 20 ms 发送一个带序号和采集时间的二进制帧。后端通过流式 Paraformer 和 FSMN-VAD 输出 `partial_transcript` 与 `final_transcript`，并用 CAM++ 将最终语句聚类为两个说话人。

客户端保留未确认帧并支持短线重连；后端返回 `audio_ack` 后才释放缓冲。结束会话时，实时录音和最终语句被交给普通分析任务，因此情绪、风险、质检和摘要仍遵循转写优先流程。

## 推理资源协调

实时 ASR 的交互延迟优先级最高。`InferenceGate` 在实时会话活跃时暂停参考音频识别和 TTS 合成队列，避免多个大模型争抢同一 GPU。离线分析和 TTS 使用独立队列；CosyVoice 运行在独立 Conda 环境和本机端口，主服务通过带令牌的 HTTP 请求调用。自定义音色使用 Fun-CosyVoice3 零样本推理，默认音色使用按需加载的 CosyVoice-300M-SFT；两种推理由同一进程锁串行执行。

## 存储

SQLite 保存任务、模块状态、会话、语句、音色和 TTS 任务元数据。文件保存在 `backend/data/jobs`、`backend/data/realtime` 和 `backend/data/tts`，默认保留 7 天。音频响应支持 HTTP Range。
