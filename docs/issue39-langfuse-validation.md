# Issue #39：Langfuse 验收记录

基线：2026-10-17 从 `origin/main` 的 `bd51974007d1668a8938e2f530588f05fc64c2e4` 新建 Worktree。Aegra CLI/API 锁定 0.10.8。Issue #37 已关闭，前端 Agent Execution Timeline 已在 main；本次未改前端。以下状态只陈述本轮证据，`PASS` 不等于生产/真实 Kubernetes 验收。

| 编号 | 状态 | 本轮证据与边界 |
| --- | --- | --- |
| A01 无 Key 关闭 | PASS（配置级） | 单测证明无 Key 时 API `OTEL_TARGETS=''`、`OTEL_CONSOLE_EXPORT=false`，但模型仍配置宿主机 7890 代理；主机 Langfuse 环境变量未继承。 |
| A02 模式覆盖 | PASS（配置级） | 参数测试覆盖全部七种本机 API 模式：无论 Langfuse Key 是否存在，API 模型请求均使用宿主机 7890；有效 Key 自动配置导出。`dev-web` 只有前端，委托 dev01 API。正式、dev01、隔离测试 Compose 基础文件均固定给 API 配置代理。 |
| A03 源文件安全 | PASS（单测） | 测试权限、属主、非普通文件、符号链接、缺失、重复、格式、URL、相对路径与异常不回显假密钥；未读取真实密钥。 |
| A04 子进程隔离 | PASS（单测） | 全部七种本机 API 模式中，仅 API 环境获得 7890 代理；有 Key 时也仅 API 获得三个 Langfuse 字段。Web/Mock/Tunnel/Preflight 无字段。 |
| A05 合成普通对话 | PASS（Cloud API + UI） | dev01 独立测试项目使用真实模型完成合成 Run，状态 `success` 且 SSE 正常结束；Langfuse Japan Public API 以 Session ID 查到 6 条 `CHAIN`/`GENERATION` observation 和一个 Trace。登录后的 Langfuse 页面打开该 Trace，并显示 `LangGraph` 与 `ChatOpenAI` observation。 |
| A06 合成 Tool Calling | BLOCKED | 未执行云端 LLM → Tool → LLM 与 Tool Call ID 核验。 |
| A07 Summary | BLOCKED | 未执行能触发摘要的多轮云端合成样例；最终采用/回退仍须结合审计。 |
| A08 网络/Key 失效 | PARTIAL | 隔离 API 的单次模型调用将代理改为关闭端口后报 `OpenAIConnectionError`，未发生直连回退；401、超时与断网场景未运行。 |
| A09 关闭追踪 | NOT RUN | 无 Key 的配置级 OFF 已测；移除 Key 并重启后的新 Run 与 Batch 队列尚未实测。 |
| A10 后端回归 | PASS（本地） | 更新后 Ruff、`git diff --check` 通过；全量 pytest `371/371` 通过。CI 须以本次提交后的最新 HEAD 为准。不更改 Golden 与历史 B06=FAIL。 |
| A11 既有前端进度 | PASS（CI/静态） | 前端文件未改；CI Web lint/build 通过，没有进行浏览器联调。 |
| A12 真实安全边界 | PASS（本轮操作） | 已仅重建 dev01 正式 API，并核对 Healthy、代理变量、`host.docker.internal=172.17.0.1` 和两个目标域名的 CONNECT 200；数据库、Redis、Web、Kubernetes MCP 未重建。未发起真实 Kubernetes Run，其内容在 Cloud 的运行级范围仍未核验。 |

证据等级：配置/单测证明环境构造；隔离 Run、Langfuse Public API 与已登录的 Cloud UI 证明这条合成链路已导出到云端并可在页面查看。Tool Calling、Summary 的父子 Span 与真实 Kubernetes 数据范围仍无运行级证据。`UNKNOWN` 项不可按预期推断为成功。合成样例只使用 Mock Reader 与合成提问，没有保存 Prompt、输出、Secret、Header、kubeconfig 或 Memory 内容。

## 复现与填写

离线：复用 Host 已有 `server/.venv` Runtime，没有下载或升级依赖。Ruff、`git diff --check` 通过，全量 pytest：`371 passed`。Compose 配置确认仅 API 容器接收 `HTTP_PROXY`、`HTTPS_PROXY` 与 `NO_PROXY`；全部 Compose 入口使用 `host.docker.internal:7890`，有无 Langfuse Key 均如此。Mac 本机经 `127.0.0.1:7890` 无凭据访问当前 HTTP 模型端点返回 401（证明请求已抵达端点），经同一代理访问 Langfuse 公共首页返回 200；Mac 原生 API 的完整 Run 尚未实测。CI 的 Python、Web lint/build 与 Compose 结果以最新 HEAD 为准；本地 Web 浏览器回归 NOT RUN。

dev01 实施与网络测试：mihomo 的 `allow-lan: true` 保留，移除 `lan-allowed-ips`，将 `bind-address` 设为 `"*"`；因现有 7890 上还有两个带专门策略的显式 listener，另外添加 Docker 网桥 `172.17.0.1` 和原 LAN 地址的 listener，保留原有 listener 不变。配置校验与服务重启通过；容器向 `api.deepseek.com:443`、`jp.cloud.langfuse.com:443` 的 HTTP CONNECT 均为 200。三项已验证的 Langfuse Key 写入 dev01 私有根目录 `.env`（0600），不输出值；正式 API 单独重建且 Healthy。隔离项目使用已有镜像及独立数据库/Redis 卷，真实模型调用和一轮合成 Run 成功；Session `f8cfd719-0fef-4d85-89e4-01ff0fa15c76` 对应 [Trace `9c29ae75179cb043ae6d93fb48e5cd0a`](https://jp.cloud.langfuse.com/project/cmvb1dbq1001kad0gk75svlc6/traces/9c29ae75179cb043ae6d93fb48e5cd0a)，Langfuse Public API 查询返回 6 条 observation；登录后的页面显示该 Trace 标题及 `LangGraph`、`ChatOpenAI` observation。隔离项目及独立卷随后清理。

云端：先确认独立的本机 Mock API、端口、PostgreSQL/Redis、Compose 项目与卷，再按[设计与操作说明](issue39-langfuse-observability.md)用合成 Thread/Run 核验。记录以下脱敏字段：本地时间/UTC、场景、Thread ID、Run ID、Langfuse Trace ID/链接、Root/LLM/Tool/Summary 是否实际可见、父子关系、State/History 的 Tool Call ID、`context_summary` 审计状态、401/超时结果。不要记录 Prompt、输出、密钥或完整环境变量。未看到 Cloud Trace 时保持 `BLOCKED` 或 `FAIL`，不得将 exporter attached 视为 PASS。
