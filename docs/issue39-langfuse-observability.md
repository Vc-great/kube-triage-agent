# Issue #39：本机 Mock 的 Langfuse Trace

本期只使用 Aegra v0.10.8 自带的 OpenTelemetry/OpenInference。`scripts/dev.py` 在明确开启的 `mock`、`mock-window`、`mock-summary` 模式中，把三个 Langfuse 配置及 `OTEL_TARGETS=LANGFUSE` 交给本机 API 子进程。Aegra 把 Trace 通过 HTTPS 送到 Langfuse Cloud Japan。仓库不安装 Langfuse SDK、CallbackHandler 或 Collector，也不改变 Graph、SSE、工具和权限逻辑。

## 配置和启动

1. 在**当前 Worktree** 的 `.local/dev.env` 添加 `LANGFUSE_TRACING_ENABLED=true`。此文件仍须为 0600；开关只接受小写 `true` 或 `false`。不配置时为 `false`。
2. 只在已获授权的私有源 `.env` 中放 `LANGFUSE_SECRET_KEY`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com`。源文件必须是当前用户拥有的普通文件、非符号链接、权限恰为 0600。若该文件不在当前 Worktree 根目录，向 `.local/dev.env` 添加 `LANGFUSE_ENV_FILE=/绝对路径/私有.env`。这是用户显式指定的只读源路径；启动器不会搜索其他位置，也不会复制密钥。
3. 确认输入和 Mock MCP 数据均为合成、无敏感信息，然后运行 `make dev-mock`、`make dev-mock-window` 或 `make dev-mock-summary`。`make dev-status` 与启动输出只显示 `on`、`off`、`forced_off`，不会显示密钥。

`make dev`、`make dev-web`、所有 Memory 模式和正式 Compose 即使存在密钥或开关为 `true` 也强制关闭。正式 Compose 明确设置 `OTEL_TARGETS=''`。允许的 Mock 模式若显式开启但缺文件、权限/属主不符、重复/缺失字段、格式错误或 URL 不合规，会以不含字段值的错误码拒绝启动。私有文件只提取上述三个键；其他行不作为 shell 代码执行或注入子进程。`OTEL_SERVICE_NAME=kube-triage-agent-mock`、`OTEL_CONSOLE_EXPORT=false` 固定由启动器生成。不要把完整 OTLP 路径写入 `LANGFUSE_BASE_URL`。

关闭时将 `.local/dev.env` 中的开关改为 `false` 或删除，并在用户确认当前服务归属后重启**本 Worktree 自己的** Mock 开发进程。关闭后新 Run 不应导出；此前 Batch 队列仍可能上传，云端旧 Trace 不会自动删除。不要以服务退出时仍出现旧 Trace 推断开关失效。

## 隐私和可观察范围

Cloud Trace 可能包含完整 Prompt、模型输出和 Mock ToolMessage。Mock Reader 并不能保证任意用户输入都安全：手动测试只能用全新合成 Thread、合成问题和合成数据，不得输入真实 Pod/Event/Log、历史会话、密钥、kubeconfig、原始 Header 或 Memory 内容。不要在 Run metadata 里放这些内容。密钥不进 Web、Mock MCP、SSH 隧道、日志、Trace metadata 或 Git。不得为了导出成功关闭 TLS/CA 校验。

Aegra 的自动 Span 可用于核对 Graph/LLM/Tool 的时间线、异常和关联。Aegra v0.10.8 的 Trace context 会设置 `langfuse.session.id=thread_id`，并在 `langfuse.trace.metadata.run_id`、`thread_id`、`graph_id` 写运行标识。OTel Trace ID 与 Aegra Run ID 是不同的标识；以实际云端属性为准。自动埋点不保证能看到 Summary 最终采纳、fallback/cache_hit、同一 Tool Call ID 或浏览器显示的 SSE 内容。这些用现有 `context_summary` 审计/Progress、Aegra State/History 和浏览器网络记录核对；缺少时标 `UNKNOWN`。若模型异常被转换为普通 `AIMessage`，Span 可能显示成功，须结合结构化审计判断。Token/费用只在真实 Provider Usage 可得时记录，不按代理响应推算。

## 手动云端验收与排障

先按[验收记录](issue39-langfuse-validation.md)检查独立端口、数据库/Redis、Compose 项目与当前 supervisor 归属。现有 `make dev*` 使用固定端口和开发库；如果稳定环境占用，**不要启动、停止或覆盖它**。由环境所有者选择独立实例或安排维护窗口。不能确认隔离时只做离线测试，把 Cloud E2E 记为 `BLOCKED`。

在安全隔离的 Mock API 上，打开本 Worktree 的 Web，输入该实例自己的 Demo API Token。界面会调用 `POST /threads` 创建全新 Thread，随后通过 `POST /threads/{thread_id}/runs/stream` 发起 Run。先发无工具的合成问候，再发需要 `pods_list`/`pods_get` 的合成问题，最后在 `mock-summary` 下连续多轮触发摘要。记录 Aegra Thread/Run ID 与 UTC 时间，在 Langfuse Japan 项目按 Session（Thread ID）或 metadata 的 Run ID 搜索，核对 Root、LLM → Tool → LLM、Summary LLM、状态/耗时和父子关系。通过 `GET /threads/{thread_id}/state` 与 `GET /threads/{thread_id}/history` 检查 `tool_call_id`，并对照 `context_summary` 审计。只保存脱敏的 ID、状态和 Trace 链接，不截图包含 Prompt、ToolMessage 或密钥的页面。只有**实际在 Langfuse 页面找到 Trace** 才将云端项标为 PASS；exporter attached 日志、Mock 单测或连接成功都不算。

云端运行前及保存证据前逐项检查：

- [ ] 使用新建的合成 Thread；问题和 Mock fixture 不含真实 Pod/Event/Log、用户内容或 Memory。
- [ ] Run metadata、可见 Prompt、LLM 输出和 ToolMessage 不含 Secret、Token、kubeconfig、原始 Header 或私人 URL 参数。
- [ ] API 连接的仅是 Mock MCP，Repair/Memory 均关闭，端口、数据库/Redis 和 Compose 项目属于隔离实例。
- [ ] 截图或链接只交给授权审阅者；公开 PR 仅写脱敏 ID、状态及覆盖缺口。
- [ ] 停止后复核新 Run 不再导出，并区分旧 Batch 队列与既有云端数据。

401/403 时先检查项目与公私钥匹配、源文件权限、Cloud Japan URL；网络异常检查 DNS、代理和 TLS。只记录 HTTP 状态/安全错误码，不打印 Authorization Header 或 Key。网络故障不能影响诊断输出与 Kubernetes 安全边界；此点必须经独立故障测试才算验收。Trace 不能替代浏览器 SSE Inspector，也不是生产日志或评测账单。
