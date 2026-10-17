# Issue #39：本机 API 模式的 Langfuse Trace

本期只使用 Aegra v0.10.8 自带的 OpenTelemetry/OpenInference。当前机器项目根目录 `.env` 中有完整有效的三项 Langfuse 配置时，每个本机 API 模式（`real`、`memory-*`、`mock*`）自动设置 `OTEL_TARGETS=LANGFUSE`；正式、dev01 与隔离测试 Compose 入口也自动叠加 `infra/langfuse.compose.yaml`。Aegra 把 Trace 通过 HTTPS 送到 Langfuse Cloud Japan。仓库不安装 Langfuse SDK、CallbackHandler 或 Collector，也不改变 Graph、SSE、工具和权限逻辑。`make dev-web` 只有前端，Trace 取决于其连接的 dev01 API 配置。

## 配置和启动

1. 在**当前 Worktree 根目录** 的私有 `.env` 放 `LANGFUSE_SECRET_KEY`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com`。文件必须是当前用户拥有的普通文件、非符号链接、权限恰为 0600。新 Worktree 若没有自己的 `.env`，启动会失败；启动器不会从其他 Worktree 搜索、复制或修改凭据。
2. 运行所需 `make dev-*` 模式；完整有效的 Key 自动开启该 API 的导出，无须额外开关。`make dev-status` 与启动输出只显示 `on`、`off` 或 `remote`，不会显示密钥。`real` 模式会访问真实 Reader/Repair 配置；云端 Trace 可能包含真实集群内容，先确认该数据可发送到 Langfuse Cloud Japan。

所有本机 API 模式在没有 Key 时关闭导出；三项配置完整有效时自动开启，并以 `kube-triage-agent-<mode>` 区分服务名。`make dev-web` 不创建本机 API，因而不会把 Key 交给 Web；其状态显示 `remote`，须在 dev01 API 端配置 Key 并重建服务。普通原生开发配置解析会忽略 `.env` 中的 Langfuse Key，API 环境构造时才单独校验；若权限/属主不符、重复/缺失字段、格式错误或 URL 不合规，会以不含字段值的错误码拒绝启动。其他 Compose 字段不注入原生开发子进程，也不执行 shell 代码。`OTEL_CONSOLE_EXPORT=false` 固定由启动器生成。不要把完整 OTLP 路径写入 `LANGFUSE_BASE_URL`。旧字段 `LANGFUSE_TRACING_ENABLED` 不再控制导出；如需关闭，请移除三项 Key 并重启对应 API。

## Compose 与 dev-web

正式 Compose 基础文件始终 `OTEL_TARGETS=''` 且不映射 Langfuse Key。对应机器的私有根目录 `.env` 中三项配置完整有效时，`./scripts/compose.sh config --quiet` 和 `./scripts/dev01-compose.sh config --quiet` 会自动加入覆盖层；隔离测试使用 `python3 scripts/compose_with_langfuse.py test <独立项目名> config --quiet`。测试文件不会与正式基础文件叠加。入口会清除 Host 环境中的 Langfuse 字段，只使用通过 `.env` 校验的值；覆盖层仅把 Key 给 API，固定 Japan BASE_URL、`OTEL_TARGETS=LANGFUSE` 和禁用控制台导出。`make dev-web` 连到的 dev01 API 在其根目录 `.env` 具备 Key 且重建 API 后才会产生 Trace。修改 `.env` 不会改变已经运行的容器；dev01 须由环境所有者在维护窗口部署。

Compose 覆盖层无法通过格式校验证明 Key 属于预期项目，也不会替你审查真实数据。先核对目标 API、项目/卷归属、数据范围和访问控制；不要把 `docker compose config` 的完整输出贴到日志或 PR，因为其中可能含 Key。运行时不改变 Reader/Repair 权限，但正式 API 的输入、输出和工具结果可能被导出，故不在此任务中自动部署远端或对真实集群运行云端 Smoke。

关闭追踪时，移除对应机器根目录 `.env` 的三项 Langfuse Key，并在确认服务归属后重启**本 Worktree 自己的** API 开发进程，或通过相同 Compose 入口重建对应 API。关闭后新 Run 不应导出；此前 Batch 队列仍可能上传，云端旧 Trace 不会自动删除。不要以服务退出时仍出现旧 Trace 推断开关失效。

## 隐私和可观察范围

Cloud Trace 可能包含完整 Prompt、模型输出和 ToolMessage。Mock Reader 也不能保证任意用户输入都安全；验证阶段仍应使用全新合成 Thread、合成问题和合成数据。`real`/Memory 模式开启后可能发送真实 Pod/Event/Log、历史会话或 Memory 内容，使用前须按实际数据授权与保留政策审查。不要在 Run metadata 里放密钥、kubeconfig、原始 Header 或私人 URL 参数。密钥不进 Web、Mock MCP、SSH 隧道、日志、Trace metadata 或 Git。不得为了导出成功关闭 TLS/CA 校验。

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
