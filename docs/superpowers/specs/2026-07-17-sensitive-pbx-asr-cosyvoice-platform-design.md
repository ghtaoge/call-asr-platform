# 企业通话智能分析平台增强设计

## 1. 背景

现有 Call ASR Platform 已支持双声道录音分析、浏览器麦克风实时识别、逐句时间戳、声学情绪、敏感词扫描、DeepSeek 摘要和 CosyVoice TTS。当前实现适合本地演示，但线上使用暴露了四个问题：

1. 敏感词来自本地 JSON，缺少多租户管理、批量导入、版本、审计和热更新。
2. 实时识别只支持浏览器麦克风，不能接收 PBX 的真实手机通话。
3. 实时 ASR 使用单执行线程且推理粒度过小，无法满足生产并发和延迟目标。
4. CosyVoice 依赖宿主机手工启动的 Conda 进程，未运行时用户提交后才看到“工作进程不可用”。

本设计将系统升级为可承载多租户、20-100 路 SIPREC 实时通话的模块化平台，同时保留现有上传分析和浏览器麦克风入口。

## 2. 已确认约束

- 多租户，每个企业的敏感词、PBX 配置、通话数据和权限必须隔离。
- 单租户敏感词规模为 10 万至 100 万。
- 敏感词修改后 5 秒内对正在进行的通话生效。
- 匹配采用精确匹配，并统一大小写、全半角和空白符；不支持拼音、谐音或模糊匹配。
- 敏感词使用低、中、高、严重四级，分别使用黄、橙、红、深红。
- 管理员可直接修改并发布，其他用户只读。
- PBX 使用 SIPREC，媒体为双向 G.711 A-law/μ-law。
- 销售与客户根据 SIPREC 参与方号码和企业分机号规则自动判定。
- 首期并发目标为 20-100 路实时通话。
- 实时字幕 P95 延迟小于 800ms，离线识别 P95 RTF 小于 0.3。
- 生产资源为单机两张 24GB NVIDIA GPU。
- PostgreSQL 保存业务数据，Redis 提供队列、版本广播和实时状态。
- 主应用、推理服务和前端均部署在 Linux Docker 环境。
- 模型在发布阶段离线下载，从受控模型仓库以只读卷挂载。
- CosyVoice 使用独立 Linux GPU 容器。

## 3. 范围

### 3.1 本期包含

- 敏感词管理页面、CRUD、启停、等级、分类、导入导出、版本和审计。
- 百万级敏感词编译、匹配、增量热更新和活跃租户缓存。
- SIPREC 信令、元数据、SDP、双向 RTP、G.711 解码和角色识别。
- PBX 实时字幕、风险事件、通话状态和结束后异步分析。
- 独立实时 ASR 和离线分析服务，GPU 隔离、批处理和容量保护。
- CosyVoice 容器化、健康检查、队列、自动恢复和明确的页面状态。
- 多租户权限、安全边界、监控、压测、故障恢复和渐进上线。

### 3.2 本期不包含

- 外呼控制、坐席软电话、PBX 管理或通话路由。
- 500 路以上的分布式容量承诺。
- 敏感词拼音、谐音、同音字、语义或正则模糊匹配。
- 自定义敏感词颜色和任意等级体系。
- 使用实时字幕直接执行自动处罚或阻断通话。

## 4. 总体架构

系统采用“模块化业务后端 + 独立媒体和推理服务”。

```text
PBX SIPREC
    |
    v
siprec-gateway ---- gRPC audio ----> asr-realtime (GPU 0)
    |                                      |
    |                                      v
    +---- encrypted spool           Redis Streams
                                           |
Browser microphone ------------------------+
                                           v
Vue web <---- REST/WebSocket ---- app-api
                                     |
                         PostgreSQL / Redis / shared storage
                                     |
                                     +---- analysis-worker (GPU 1) ---- DeepSeek
                                     |
                                     +---- cosyvoice-worker (GPU 1)
```

### 4.1 服务职责

- `web`：Vue 工作台、敏感词管理、实时通话和 TTS 页面。
- `app-api`：认证、租户隔离、业务 API、通话查询和 WebSocket 推送。
- `sensitive-compiler`：构建基础/增量自动机快照并发布版本。
- `siprec-gateway`：SIPREC、RTP、媒体缓冲、角色映射和降级落盘。
- `asr-realtime`：GPU 0 上的流式 VAD、ASR、动态微批次和实时事件。
- `analysis-worker`：GPU 1 上的离线转写、情绪、质检和摘要编排。
- `cosyvoice-worker`：GPU 1 上的默认音色和声音复刻。
- `PostgreSQL`：租户、权限、词库、版本、通话、任务和审计。
- `Redis`：实时状态、事件流、任务队列、版本广播和分布式锁。

服务通过内部网络通信。外部 PBX 只能访问 Gateway 的 SIP/RTP 端口，浏览器只能访问反向代理暴露的 Web/API/WebSocket。

## 5. 多租户与权限

所有业务表都包含 `tenant_id`，并使用 PostgreSQL Row Level Security 或等价的强制查询作用域。`tenant_id` 只从登录令牌或服务身份解析，不接受前端请求体提供的值。

角色分为：

- `tenant_admin`：敏感词增删改、批量操作、发布、PBX 规则配置和查看审计。
- `tenant_user`：查看本租户通话、风险、摘要和只读敏感词。
- `platform_operator`：查看服务健康、队列和基础设施指标，不默认读取通话正文。

管理员的每次写入直接创建新版本并发布，不设置双人审核流程。批量导入需要先校验再由同一管理员确认发布。

## 6. 高性能敏感词中心

### 6.1 数据模型

`sensitive_words`：

- `id`, `tenant_id`
- `word`, `normalized_word`
- `level`: `low | medium | high | critical`
- `category`, `enabled`, `remark`
- `created_by`, `updated_by`, `created_at`, `updated_at`

对 `(tenant_id, normalized_word)` 建立唯一索引。

`sensitive_versions`：

- `tenant_id`, `version`
- `base_version`, `change_count`, `total_count`
- `status`: `building | ready | failed | active`
- `artifact_path`, `checksum`, `published_by`, `published_at`

`sensitive_audit_logs` 保存操作人、动作、对象、修改前后值、批量任务和时间。导入任务单独保存文件摘要、校验结果、成功/失败数和错误文件路径。

### 6.2 标准化与位置映射

词库和通话文本使用同一标准化函数：Unicode NFKC、拉丁字母小写、全角转半角、删除配置允许的空白符。标准化文本同时生成每个字符到原文本索引的映射，使匹配区间可以准确还原到原句。

不进行繁简体、拼音、同音字或语义扩展。该边界保证匹配确定性和吞吐量。

### 6.3 两层 Aho-Corasick

匹配器使用 Rust 实现的 Aho-Corasick，避免 Python 字典节点在百万词下产生过高内存开销。

- 基础层是租户已发布大词库的只读编译快照。
- 增量层只包含上次基础快照后的新增和修改。
- 删除和禁用生成 tombstone，过滤基础层中的旧结果。
- 基础层和增量层同时扫描，合并后执行最长词优先和最高等级规则。
- 增量数量或内存达到阈值时后台压实为新基础快照。
- 新快照校验 checksum 后原子切换；旧扫描完成后再释放旧快照。

修改发布后，编译器写入 PostgreSQL 版本并通过 Redis 广播。活跃节点在 5 秒内加载增量快照。节点还会周期性对账数据库最新版本，避免广播丢失导致长期落后。

### 6.4 活跃租户缓存

编译快照保存在共享只读卷。识别节点只加载当前存在活跃通话的租户，使用 LRU、引用计数和内存上限回收空闲快照。每个通话固定记录使用过的词库版本；热更新后下一条最终分句使用新版本，已发布事件不回溯重写。

### 6.5 命中展示

最终分句完成后进行正式匹配。命中事件包含词、等级、分类、原文位置、角色、时间点和词库版本。页面颜色为：

- `low`：黄
- `medium`：橙
- `high`：红
- `critical`：深红

临时字幕可做非正式提示，但不计入风险统计和审计，避免字幕修正造成闪烁或误报。

## 7. SIPREC/PBX 接入

### 7.1 Gateway 技术边界

Gateway 使用 Go 和成熟 SIP/RTP 库，不在 FastAPI 事件循环内处理媒体包。它接收 SIPREC INVITE，解析 multipart、SDP 和 SIPREC XML，并返回标准 SIP 响应。

XML 解析禁止外部实体，并限制消息大小、嵌套深度、参与者数量和媒体数量。

### 7.2 租户与角色识别

租户由 PBX 来源地址、证书或 Trunk 标识映射。角色由 SIPREC 参与方号码和租户分机规则判定：企业分机为销售，外部号码为客户。无法唯一判定时角色为 `unknown`，页面允许有权限用户后续修正。

不使用固定 RTP 顺序猜测角色。

### 7.3 RTP 处理

Gateway 根据 SDP 分配媒体端口并支持 PCMA/PCMU。每路 RTP 执行：

1. SSRC、序号和时间戳校验。
2. 抖动缓冲、乱序重排和重复包过滤。
3. 短时丢包补偿并记录丢包质量指标。
4. G.711 解码为 PCM。
5. 8kHz 重采样到 16kHz。
6. 按 20ms 帧通过内部双向 gRPC 发送。

媒体帧包含 `tenant_id`, `call_id`, `stream_id`, `speaker`, `sequence`, `captured_at_ms` 和 PCM payload。ASR 返回累计确认序号，Gateway 只在确认后释放补传缓冲。

### 7.4 生命周期与恢复

通话状态为：

`connecting -> active -> finalizing -> completed`

异常标记包括 `role_pending`, `media_interrupted`, `asr_degraded`, `pbx_aborted`。

幂等键为 `tenant_id + SIPREC session_id`。SIP 重传和 Gateway 重启不得创建重复通话。

Gateway 同时写入本地加密临时音频。ASR 暂时断开时继续接收 RTP并缓冲；恢复后补传实时窗口内数据。超出窗口的数据保留到通话结束并自动进入离线补识别。BYE、RTP 超时和异常断线进入同一结束流程。

### 7.5 网络安全

- SIP 信令优先使用 TCP/TLS。
- PBX 地址和租户 Trunk 加入白名单。
- RTP 运行在企业专网或 VPN。
- 内部 gRPC 使用 mTLS。
- 每租户限制并发会话、RTP 端口和信令速率。

## 8. ASR 性能优化

### 8.1 当前瓶颈

当前实时管理器只有一个执行线程，所有会话串行；20ms 帧可能直接触发模型调用；CAM++ 按会话预热；模型冷启动落在第一通电话；实时、离线和 TTS 可能争抢同一资源。

### 8.2 GPU 0：实时服务

`asr-realtime` 启动时加载并预热流式 Paraformer、VAD 和必要标点模型。预热完成前 readiness 失败。

- 输入仍为 20ms PCM 帧。
- 每会话聚合到 160-240ms 推理块。
- 调度器每 40ms 检查各会话，以最大批次和最老任务延迟预算形成动态微批次。
- 模型使用 FP16 与 ONNX Runtime CUDA/TensorRT。
- 每个会话保存独立流式缓存。
- 临时字幕每 300-500ms 更新。
- VAD 端点后立即生成最终分句和时间戳。
- SIPREC 双路音频已带角色，不运行 CAM++。
- 浏览器单麦克风模式继续使用 CAM++，说话人嵌入按最终分句批处理。

### 8.3 GPU 1：离线分析与 TTS

离线音频先 VAD 切段，多个短段批量送入模型。双声道并行解码后按时间戳归并。情绪使用批处理，质检和摘要保持异步。

CosyVoice 和离线分析通过 Redis 队列协调。实时 GPU 不接收离线或 TTS 工作；GPU 1 为 TTS 设置单任务并发和较低优先级。

### 8.4 容量保护

- 每租户限制实时并发。
- 达到容量时优先现有实时通话，新通话进入有界短队列。
- 离线和 TTS 根据 GPU 指标自动降速。
- 队列满时返回明确的容量错误，不无限积压。

核心指标包括首字延迟、临时字幕延迟、最终句延迟、RTF、GPU 利用率/显存、队列长度、丢帧、降级和模型重启次数。

验收要求：100 路模拟负载下实时字幕 P95 小于 800ms；离线 RTF P95 小于 0.3；准确率相对当前基线下降不超过 1%。

## 9. CosyVoice 容器化

### 9.1 部署

`cosyvoice-worker` 镜像锁定官方提交和 Python 依赖。Fun-CosyVoice3 和 CosyVoice SFT 模型从受控仓库离线获取，以只读卷挂载到 `/models`。

容器启动时加载、预热并执行短句自检。只有模型、输出文件和音频样本检查通过，`/health/ready` 才成功。Docker Compose 配置 GPU 1、自动重启、健康检查和日志限制。

主后端通过 `http://cosyvoice-worker:18081` 访问，并禁用系统代理。生产不再依赖宿主机 Conda 或 localhost 进程。

### 9.2 任务状态

页面通过 `/api/tts/health` 展示：

- `starting`：模型加载中，禁用提交。
- `ready`：可提交。
- `busy`：可提交并显示排队。
- `unavailable`：禁用提交并显示稳定错误码和中文原因。

任务先写入 PostgreSQL，再进入 Redis 队列。Worker 心跳中断时排队任务保持 queued；超过任务超时后进入可重试失败。Worker 恢复后继续未过期任务，不要求重启主后端。

默认音色无需授权。自定义音色要求确认授权、3-30 秒参考音频和七天清理。日志不得记录合成文本、参考文本、密钥或真实文件路径。

## 10. 页面设计

### 10.1 敏感词设置

页面包含：

- `敏感词库`：游标分页、搜索、等级/分类/状态筛选和批量操作。
- `批量任务`：导入校验、进度、结果和失败文件。
- `版本记录`：版本、变更数量、词数、发布人和发布时间。
- `操作审计`：操作人、动作、对象和修改前后内容。

表格字段为敏感词、等级、分类、状态、备注、更新时间和操作。顶部提供新增、批量启停、导入和导出。百万级列表只使用服务端分页，不把全量数据载入浏览器。

### 10.2 实时通话

新增实时通话列表，显示租户、销售、客户、来源、开始时间、状态、字幕延迟和风险数。PBX 与浏览器通话复用逐句组件，通过来源标签区分。

命中词在原文中标色，悬停展示等级、分类、版本和时间点。风险面板可按等级、角色和分类筛选。

### 10.3 TTS

TTS 页面先读取 Worker 健康状态。未就绪时禁用提交并显示原因；繁忙时允许排队。默认音色和自定义音色继续使用分段切换控件。

## 11. API 与事件

### 11.1 管理 API

- `GET/POST /api/admin/sensitive-words`
- `PATCH/DELETE /api/admin/sensitive-words/{id}`
- `POST /api/admin/sensitive-words/batch`
- `POST /api/admin/sensitive-imports`
- `GET /api/admin/sensitive-imports/{id}`
- `POST /api/admin/sensitive-imports/{id}/publish`
- `GET /api/admin/sensitive-versions`
- `GET /api/admin/audit-logs`

所有列表使用游标分页。批量导入异步处理，不占用 HTTP 请求。

### 11.2 实时 API

- `GET /api/realtime/calls`
- `GET /api/realtime/calls/{call_id}`
- `WS /ws/calls/{call_id}`

WebSocket 事件统一为 `call_status`, `partial_transcript`, `final_transcript`, `risk_update`, `quality_update`, `analysis_status` 和 `error`。事件包含递增序号，客户端可带最后确认序号重连。

### 11.3 TTS API

- `GET /api/tts/health`
- 现有默认音色、克隆、创建任务、查询和音频接口保持兼容。

## 12. 错误处理

- 敏感词编译失败时继续使用上一稳定版本，不发布半成品。
- Redis 广播丢失时通过 PostgreSQL 定期对账补加载。
- SIPREC 无 RTP 时标记媒体中断并正常结束诊断任务。
- RTP 乱序、重复和短时丢包由 Gateway 修复并计入质量指标。
- 实时 ASR 不可用时 Gateway 落盘，页面显示降级，恢复后补传或转离线。
- 单会话异常不允许重启整个 ASR 服务。
- CosyVoice 未就绪时前端禁止提交；运行中失败保留任务并允许重试。
- PostgreSQL 暂时不可用时停止管理写入和新任务登记，Gateway 在有界时间内继续本地落盘并在恢复后补交。

所有公开错误使用稳定错误码和中文消息。内部异常、路径、模型栈和密钥不得返回前端。

## 13. 测试与验收

### 13.1 功能和算法

- 标准化、位置映射、四级命中、最长词、最高等级、增量层、tombstone。
- 租户隔离、管理员写入、普通用户只读、审计完整性。
- 100 万词编译时间、快照大小、热更新时间、扫描吞吐和峰值内存。

### 13.2 SIPREC

使用固定 SIP/SDP/XML 和 RTP 样本回放 PCMA、PCMU、乱序、丢包、重复、BYE、超时和异常断线。验证角色映射、时间戳、双路录音和幂等性。

### 13.3 性能

按 20、50、100 路分阶段压测。采集实时延迟分位数、离线 RTF、GPU、队列、丢帧和准确率。100 路不达标不得全量上线。

### 13.4 故障与安全

- 运行中重启 ASR、Redis、Gateway 和 CosyVoice。
- 验证音频恢复、任务不重复、旧词库持续服务和任务可重试。
- 测试跨租户越权、XXE、超大 SIP/XML、非法 RTP、导入公式注入和上传限制。
- 浏览器覆盖敏感词 CRUD/导入、实时标色、PBX 通话、TTS 健康状态和移动端布局。

## 14. 上线顺序

该范围拆成四个独立、可回滚的实施变更。每个变更分别编写实施计划、完成测试并发布，不使用一个超大改动同时切换全部基础设施。

实现顺序：

1. CosyVoice 容器化和健康状态，消除当前不可用问题。
2. 独立 ASR 推理服务、GPU 分配、预热、批处理和性能基线。
3. PostgreSQL/Redis 多租户基础和高性能敏感词中心。
4. SIPREC Gateway、PBX 影子流量和实时页面接入。

发布阶段：

1. 影子模式接收 PBX 流，只记录和比较，不影响现网。
2. 5% 坐席启用实时字幕和敏感词告警。
3. 满足延迟、准确率、恢复和安全指标后逐步扩大。

## 15. 迁移原则

- 保留现有上传分析、URL 分析和浏览器麦克风接口。
- 现有 SQLite 数据提供一次性迁移工具，生产切换 PostgreSQL 后只读归档旧库。
- 现有 JSON 敏感词作为首个租户的初始化导入源，不再作为运行时真相源。
- 现有 WebSocket 协议在过渡期保留，统一事件协议稳定后再标记废弃。
- 当前未提交的默认音色实现不属于本设计文档提交，后续实施计划应基于当时工作区状态整合。
