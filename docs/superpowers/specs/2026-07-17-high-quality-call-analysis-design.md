# 高质量通话转写与智能质检设计

## 1. 目标

将现有“整段识别 + 占位翻译 + 规则摘要”升级为适合中文客服质检的完整通话分析工作台：

- 使用阿里开源模型在本地完成中文语音识别、VAD 断句、标点恢复和情绪识别。
- 固定双声道角色映射：左声道为销售，右声道为客户。
- 输出真实时间戳，并按时间顺序交错展示双方话轮。
- 同时提供“逐句”和“合并”两种阅读模式。
- 按四个等级识别并高亮敏感词。
- 使用 DeepSeek 官方 API 生成简要结论和结构化通话摘要。
- 将页面重构为符合中文客服、销售和质检人员使用习惯的高密度工作台。
- 使用后台任务执行耗时模型，避免长录音导致 HTTP 请求超时。

## 2. 非目标

- 不提供中英或多语言文本翻译。本期的“翻译效果”指中文语音转写质量。
- 不在本期实现单声道说话人聚类。输入约束为双声道录音。
- 不在本期重做实时 WebSocket 识别。保留后端接口，但从主操作区移除当前不完整的实时入口。
- 不在本期引入 Redis、Celery 或外部任务队列。当前部署采用单机、单进程、单模型工作线程。
- 不让 DeepSeek 参与原始语音识别、敏感词判定或情绪判定。

## 3. 已确认决策

| 项目 | 决策 |
| --- | --- |
| 录音格式 | 双声道 |
| 角色映射 | 左声道销售，右声道客户 |
| 输出语言 | 只输出高质量中文转写 |
| 分段视图 | 逐句和合并两种模式，可即时切换 |
| ASR | SenseVoiceSmall |
| 断句 | FSMN-VAD |
| 标点 | CT-Punc |
| 情绪 | emotion2vec，每个话轮分析 |
| 部署 | 阿里开源模型完全本地运行，CPU 优先准确率 |
| 敏感词 | 低、中、高、严重四级颜色 |
| 摘要 | DeepSeek 官方 API；简短结论 + 固定结构字段 |
| 任务执行 | 后台任务 + 前端轮询 |
| URL | 支持公开 URL 和带签名参数的 URL |

模型组合依据 [FunASR 官方仓库](https://github.com/modelscope/FunASR) 和
[SenseVoice 官方仓库](https://github.com/FunAudioLLM/SenseVoice) 的组合用法。

## 4. 总体架构

```text
上传文件 / 提交音频 URL
          |
          v
创建 Job 并立即返回 job_id
          |
          v
单工作线程后台执行
  1. 获取和校验音频
  2. 拆分左右声道
  3. 销售声道：VAD -> SenseVoice -> CT-Punc
  4. 客户声道：VAD -> SenseVoice -> CT-Punc
  5. 按 start_ms 合并话轮
  6. emotion2vec 分析每个话轮
  7. 四级敏感词扫描
  8. DeepSeek 生成摘要
          |
          v
SQLite 保存结果，前端轮询并展示
```

### 4.1 模型生命周期

新增 `ModelRegistry`，按需加载并缓存以下模型：

- `iic/SenseVoiceSmall`
- `fsmn-vad`
- `ct-punc`
- `emotion2vec_plus_large`

模型不得在每次 HTTP 请求中重新初始化。模型推理统一放入 `ThreadPoolExecutor(max_workers=1)`，避免阻塞 FastAPI 事件循环，并避免多个 CPU 推理任务同时抢占内存。

### 4.2 任务生命周期

任务状态：

```text
queued -> running -> completed
                  -> failed
```

处理阶段及建议进度：

| 阶段 | 进度 |
| --- | ---: |
| preparing_audio | 5% |
| transcribing_sales | 15% |
| transcribing_customer | 40% |
| merging_segments | 65% |
| analyzing_emotion | 72% |
| scanning_risks | 82% |
| generating_summary | 90% |
| completed | 100% |

任务记录 `stage`、`progress`、`error_code`、`error_message`、创建时间和更新时间。应用重启时仍处于 `running` 的任务标记为 `interrupted`，前端提供重新执行入口。

## 5. 音频与识别流水线

### 5.1 输入约束

- 支持浏览器上传的常见音频格式。
- 支持 `http://` 和 `https://` URL，包括带签名查询参数的长 URL。
- 下载最多跟随 5 次重定向。
- 音频最大 50 MB，下载和读取均采用流式大小限制。
- 拒绝空文件、无法解码的文件和没有音频流的文件。
- URL 每次解析和重定向后都校验目标地址，阻止 loopback、私网、链路本地地址和云元数据地址，防止 SSRF。

### 5.2 双声道处理

PyAV 将输入转换为 16 kHz、单声道、16-bit PCM 的左右两个 WAV 数据流：

- 左声道始终写入 `speaker=sales`。
- 右声道始终写入 `speaker=customer`。
- 如果输入不是双声道，任务以 `unsupported_channel_layout` 失败，不猜测说话人。

### 5.3 断句、识别和标点

每个声道独立运行 `SenseVoiceSmall + FSMN-VAD + CT-Punc`。读取 FunASR 返回的 `sentence_info`，每个元素转为一个原子话轮：

- `start_ms`、`end_ms` 使用模型返回的真实时间。
- `text` 使用模型和标点组件输出，不再使用空格规则拼接标点。
- 清理 SenseVoice 的语言、情绪和音频事件标签，但保留纯文本。
- 丢弃空文本和纯非语音事件。
- 生成稳定的 segment ID，不依赖插入顺序。

两个声道完成后，按 `(start_ms, end_ms, speaker)` 排序。重叠话轮保留，不强行截断；这能反映抢话和打断，并供质量评分使用。

### 5.4 逐句与合并模式

数据库只保存原子话轮。前端“合并模式”按以下规则派生：

- 只合并相邻且说话人相同的话轮。
- 两个话轮间隔不超过 1.2 秒。
- 合并后文本不超过 120 个中文字符。
- 合并后的时间范围覆盖所有子话轮。
- 敏感词位置在前端按子话轮渲染，不修改后端命中坐标。

切换显示模式不得重新调用 ASR。

## 6. 数据模型

### 6.1 Segment

现有 `Segment` 扩展为：

```text
id
session_id
speaker: sales | customer
start_ms
end_ms
text
language: zh
emotion.label
emotion.confidence
emotion.score: -1.0 .. 1.0
sensitive_hits[]
compliance_hits[]
confidence
is_final
```

兼容期内保留 `translation` 和 `target_language` 字段，但 `translation` 返回空字符串，前端不再展示。

### 6.2 Job

新增 `jobs` 表：

```text
id TEXT PRIMARY KEY
session_id TEXT
source_type TEXT
source_url TEXT NULL
status TEXT
stage TEXT
progress INTEGER
error_code TEXT NULL
error_message TEXT NULL
summary_status TEXT
created_at TEXT
updated_at TEXT
```

不保存 DeepSeek API Key。对于 URL 输入，日志不得输出完整签名查询参数；数据库可选择不保存 URL，或只保存去除 query 的脱敏地址。

### 6.3 摘要

`CallSummary` 扩展为：

```text
overview: string
customer_needs: string[]
sales_promises: string[]
risk_points: string[]
follow_up_items: string[]
next_steps: string[]
```

## 7. 情绪分析与趋势图

每个 VAD 原子话轮独立运行 `emotion2vec_plus_large`。Provider 统一模型可能返回的标签别名，并输出：

- `label`：positive、neutral、negative、angry、anxious 等产品级标签。
- `confidence`：模型对最终标签的置信度。
- `score`：用于趋势图的情绪效价，范围 `[-1, 1]`。

`score` 由标签基础效价乘以置信度得到；未知和低置信度结果回落到 0。标签映射集中在 Provider 内并有单元测试，不分散到前端。

情绪图使用 ECharts：

- 横轴为通话时间。
- 纵轴从负面到正面。
- 销售和客户分别一条曲线。
- 默认显示双方，可切换为仅客户。
- 点击数据点定位音频并滚动到对应话轮。
- 高风险和严重敏感词命中的时间点显示风险标记。
- 没有足够数据时显示空状态，不绘制误导性水平线。

## 8. 敏感词识别

沿用 JSON 词库和现有扫描器，统一四个等级的产品语义和颜色：

| 等级 | 正文颜色 | 用途 |
| --- | --- | --- |
| low | 黄色 | 提醒关注 |
| medium | 橙色 | 需要复核 |
| high | 红色 | 高风险 |
| critical | 深红色 | 严重风险 |

正文高亮保留原始文字。悬停或聚焦时显示词条、等级、分类和命中时间。右侧风险页显示各等级数量和命中列表；点击列表项定位到对应时间和话轮。

高亮不能只依赖颜色，必须同时提供等级文字或图标，保证可访问性。

## 9. DeepSeek 通话摘要

### 9.1 配置

根据 [DeepSeek 官方 API 文档](https://api-docs.deepseek.com/)：

- `DEEPSEEK_API_KEY`：必填密钥。
- `DEEPSEEK_BASE_URL`：默认 `https://api.deepseek.com`。
- `DEEPSEEK_MODEL`：默认 `deepseek-v4-pro`，质量优先。
- `DEEPSEEK_TIMEOUT_SECONDS`：默认 60 秒。

不默认使用即将弃用的 `deepseek-chat`。模型名必须可通过环境变量调整。

### 9.2 输入与输出

DeepSeek 只接收结构化文本话轮：时间、角色和文本。敏感词等级、规则命中和情绪摘要可以作为辅助上下文，但不得要求模型重新判定硬规则结果。

要求模型返回 JSON 对象，后端使用 Pydantic 严格验证：

- 字段必须存在且类型正确。
- 数组数量和每项长度有限制。
- 不接受 Markdown 代码围栏作为最终持久化格式。
- 验证失败时最多进行一次格式修复请求。

长通话采用分层摘要：先按话轮批次生成局部事实，再基于局部结果生成最终摘要。提示词明确要求不编造订单、承诺、金额和处理结果；没有证据时返回空数组。

### 9.3 失败隔离

DeepSeek 缺少 API Key、超时、限流或格式异常时：

- Job 的本地分析仍然完成。
- `summary_status` 标记为 `failed`。
- 页面保留转写、情绪和风险结果。
- 提供“重新生成摘要”操作，只重跑 DeepSeek 阶段。

## 10. API 设计

新增接口：

```text
POST /api/jobs/upload
POST /api/jobs/url
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/result
POST /api/jobs/{job_id}/retry-summary
```

创建任务返回 HTTP 202：

```json
{
  "job_id": "job_xxx",
  "session_id": "call_xxx",
  "status": "queued",
  "stage": "queued",
  "progress": 0
}
```

`GET /api/jobs/{job_id}` 返回轻量状态。只有完成或部分完成时，前端才请求完整结果，避免轮询反复传输全部转写。

保留现有 `/api/sessions/offline` 和 `/api/sessions/url` 作为兼容接口；新页面只调用 Job API。兼容接口的后续移除不属于本期范围。

## 11. 页面设计

### 11.1 顶部操作区

- 左侧显示产品名称和任务状态。
- 中间是可容纳长签名 URL 的输入框。
- 右侧是“识别”和“上传录音”主要操作。
- 删除销售/客户/未知下拉框。
- 从主操作区移除当前不完整的“实时”按钮。
- 任务执行时在顶部下方显示阶段、百分比和进度条。

### 11.2 主工作区

桌面端使用 `minmax(0, 1fr) 360px` 两栏布局：

- 左侧：音频播放器、模式控制、角色筛选、对话时间线。
- 右侧：摘要、敏感词、情绪趋势三个标签页，滚动时保持可见。

移动端改为单栏，分析区显示为底部标签页。所有固定格式控件使用稳定高度和响应式宽度，避免状态更新引发布局跳动。

### 11.3 对话时间线

- “逐句 / 合并”使用分段控制。
- “全部 / 仅销售 / 仅客户”使用分段控制。
- 销售使用青绿色，客户使用蓝色，并同时显示角色文字。
- 每条话轮显示时间、角色、情绪和识别置信度。
- 点击时间跳转音频；播放时突出当前话轮。
- 敏感词按四级颜色高亮。

### 11.4 视觉风格

- 面向中文客服和质检人员，采用安静、清晰、高信息密度的工具风格。
- 使用白色内容面、浅灰页面背景、深色正文、蓝色主要操作、青绿角色辅助色和独立风险色。
- 不使用装饰性渐变、光晕、营销式大标题或页面区块卡片化。
- 使用 Microsoft YaHei、PingFang SC 等中文系统字体优先栈。
- 按钮使用现有 Lucide 图标；不手绘 SVG。
- 卡片圆角不超过 8px，不嵌套卡片。

## 12. 错误处理

错误码至少包括：

```text
invalid_url
blocked_url
download_timeout
audio_too_large
invalid_audio
unsupported_channel_layout
asr_failed
emotion_failed
summary_missing_api_key
summary_timeout
summary_rate_limited
summary_invalid_response
interrupted
```

错误信息面向中文用户，后端日志保存技术细节但不泄露 URL 签名、API Key 或完整 DeepSeek 请求。

## 13. 测试策略

### 13.1 后端

- 双声道拆分保持左右波形且角色映射固定。
- 单声道输入返回明确错误。
- FunASR `sentence_info` 转换为真实时间戳话轮。
- 左右声道结果正确按时间交错。
- 标点来自模型输出，不执行旧规则二次污染。
- emotion2vec 标签归一化、置信度和效价分数。
- 四级敏感词命中位置和上下文。
- Job 状态和阶段进度持久化。
- 重启后处理中任务转为中断。
- DeepSeek 正常、无 Key、超时、限流、无效 JSON 和一次修复。
- URL 重定向、超时、超限、非音频、DNS 变化和 SSRF 阻断。

模型单元测试使用小型固定结果或 Provider 边界替身；另保留一条可选的本地真实模型烟雾测试，不让常规测试下载大型模型。

### 13.2 前端

- 创建上传和 URL 任务。
- 轮询阶段进度，完成后只获取一次完整结果。
- 失败、部分完成和摘要失败状态。
- 逐句/合并模式不修改原子数据。
- 角色筛选、时间跳转和播放高亮。
- 情绪曲线双方/仅客户切换及点击定位。
- 四级敏感词颜色和非颜色等级标识。
- 摘要、风险和情绪标签页。
- 桌面、平板和移动端构建与关键布局。

## 14. 验收标准

1. 4 至 10 分钟双声道中文录音可以通过文件或 URL 创建后台任务。
2. 页面在处理期间持续显示阶段和进度，不因长请求超时。
3. 输出至少包含多个带真实时间戳的话轮，而不是整段单一文本。
4. 销售和客户角色固定正确，并按实际时间交错。
5. 中文标点自然，短口头语可以独立成句。
6. 逐句和合并模式可以即时切换。
7. 情绪图显示双方曲线，支持仅客户筛选和点击定位。
8. 敏感词按四级颜色高亮，右侧可汇总并定位。
9. DeepSeek 正常时返回简短结论和五类结构化字段；失败不影响本地分析结果。
10. 页面不再显示角色下拉框、占位 `[en]` 翻译或不完整的实时入口。
11. 未配置 DeepSeek API Key 时，用户仍能完成本地转写、情绪和风险分析。
12. URL 接口不能访问本机、内网或云元数据地址。

## 15. 依赖变化

后端新增或明确使用：

- FunASR 的 FSMN-VAD、CT-Punc、emotion2vec 模型。
- 现有 `httpx` 调用 DeepSeek，无需额外 SDK。
- 标准库 `concurrent.futures.ThreadPoolExecutor`。

前端新增：

- `echarts`，用于情绪趋势图。

不新增任务队列、缓存服务或云 ASR SDK。
