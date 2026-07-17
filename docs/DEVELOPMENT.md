# Development Guide

## 后端测试

```powershell
cd backend
python -m pytest -q
```

在 Windows 临时目录权限受限时可增加 `--basetemp .pytest-tmp`。真实模型不在单元测试中加载，测试使用受控替身覆盖时间戳、模块状态、重试、实时协议、资源优先级和 TTS 生命周期。

## 前端测试

```powershell
cd frontend
npm install
npm test -- --run
npm run build
```

浏览器验收至少覆盖桌面和 390px 移动视口，并检查麦克风授权、实时临时文字、暂停/恢复、结束后异步分析、逐句播放定位、TTS 授权和错误提示。

## 模型与进程

- 主后端模型由 `app/asr/model_registry.py` 延迟加载并复用。
- 实时识别使用流式 Paraformer、FSMN-VAD 和 CAM++，可运行 `python scripts/download_realtime_models.py` 预取。
- CosyVoice 必须运行在独立 Conda Python 3.10 环境，不要把它的依赖安装进主后端虚拟环境。
- 实时 ASR 活跃时，`InferenceGate` 暂停参考音频识别和 TTS 队列；修改相关代码时必须保留成对的开始/结束调用。

## 代码边界

- API 路由只负责协议转换和公开错误，编排放在 `JobManager`、`RealtimeManager` 和 `TtsManager`。
- 基础转写只保存一次；情绪、风险和摘要使用独立产物，禁止重试某模块时覆盖基础语句。
- 模型异常、网络异常和内部路径不能直接暴露给前端；使用稳定错误码和中文公开消息。
- 音频路径必须由存储类生成，TTS 工作进程只读写配置根目录内的文件。
- 不在日志、测试样本或提交中写入 API Key、真实客户录音和完整通话文本。

## 基准测试

```powershell
cd backend
python scripts/bench_sensitive.py
```
