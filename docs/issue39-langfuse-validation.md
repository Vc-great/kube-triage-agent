# Issue #39：Langfuse 验收记录

基线：2026-10-17 从 `origin/main` 的 `bd51974007d1668a8938e2f530588f05fc64c2e4` 新建 Worktree。Aegra CLI/API 锁定 0.10.8。Issue #37 已关闭，前端 Agent Execution Timeline 已在 main；本次未改前端。以下状态只陈述本轮证据，`PASS` 不等于生产/真实 Kubernetes 验收。

| 编号 | 状态 | 本轮证据与边界 |
| --- | --- | --- |
| A01 默认关闭 | PASS（配置级） | 单测证明默认 API `OTEL_TARGETS=''`、`OTEL_CONSOLE_EXPORT=false`，主机 Langfuse 环境变量未继承；未启动进程核查云端。 |
| A02 模式隔离 | PASS（配置级） | 参数测试覆盖 real、web、Memory 三种模式，显式 true 仍不读私有源，API 导出关闭。 |
| A03 源文件安全 | PASS（单测） | 测试权限、属主、非普通文件、符号链接、缺失、重复、格式、URL、相对路径与异常不回显假密钥；未读取真实密钥。 |
| A04 子进程隔离 | PASS（单测） | 三个允许的 Mock 模式中，仅 API 环境有三个 Langfuse 字段；Web/Mock/Tunnel/Preflight 无字段。 |
| A05 合成普通对话 | BLOCKED | 新 Worktree 缺独立的根目录 `.env` 与数据库/Redis 测试实例；未执行 Langfuse 页面核验，无 Trace ID/Run ID。 |
| A06 合成 Tool Calling | BLOCKED | 未执行云端 LLM → Tool → LLM 与 Tool Call ID 核验。 |
| A07 Summary | BLOCKED | 未执行能触发摘要的多轮云端合成样例；最终采用/回退仍须结合审计。 |
| A08 网络/Key 失效 | NOT RUN | 未对独立 API 做 401、超时、断网故障注入。 |
| A09 关闭追踪 | NOT RUN | 配置级 OFF 已测；关闭后的新 Run 与 Batch 队列尚未实测。 |
| A10 后端回归 | PASS | Ruff `scripts/dev.py server/src server/tests` 通过；全量 pytest `363/363` 通过（复用 Host 现有 Aegra 0.10.8 Runtime）；不更改 Golden 与历史 B06=FAIL。 |
| A11 既有前端进度 | PASS（CI/静态） | 前端文件未改；CI Web lint/build 通过，没有进行浏览器联调。 |
| A12 真实安全边界 | PASS（本轮操作） | 未连接真实 Kubernetes、未写入/改动 dev01 正式服务或稳定服务；正式 Compose 固定 OFF。 |

证据等级：源码/配置与单元测试只证明环境构造和失败边界；Mock 模型联调、Cloud Ingestion、Langfuse UI 中真实父子 Span 与 Run/Thread 映射目前没有证据。`UNKNOWN` 项不可按预期推断为成功。云端核验前先审查测试问题、Mock 数据、Run metadata 和截图，确保无真实用户内容、Pod/Event/Log、Secret、Header、kubeconfig、Memory 内容。发现任何真实数据可能上传时停止云端步骤。

## 复现与填写

离线：本轮复用 Host 已有 `server/.venv` 的 Aegra CLI/API 0.10.8 Runtime（没有下载或升级依赖），运行 Ruff `scripts/dev.py scripts/prepare-dev01.py server/src server/tests`：PASS；根目录 `.env` 联动调整后全量 pytest：`363 passed`；`git diff --check`：PASS。新 Worktree 的 sandbox 无法写既有测试需要的忽略目录 `.local/eval-runs`；在 Host 权限下对同一 Worktree 重跑完整套件后通过。CI 的 Python、Web lint/build 与 Compose 通过；本地 Web 浏览器回归 NOT RUN。

云端：先确认独立的本机 Mock API、端口、PostgreSQL/Redis、Compose 项目与卷，再按[设计与操作说明](issue39-langfuse-observability.md)用合成 Thread/Run 核验。记录以下脱敏字段：本地时间/UTC、场景、Thread ID、Run ID、Langfuse Trace ID/链接、Root/LLM/Tool/Summary 是否实际可见、父子关系、State/History 的 Tool Call ID、`context_summary` 审计状态、401/超时结果。不要记录 Prompt、输出、密钥或完整环境变量。未看到 Cloud Trace 时保持 `BLOCKED` 或 `FAIL`，不得将 exporter attached 视为 PASS。
