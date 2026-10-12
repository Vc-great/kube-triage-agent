# Phase 2 验收记录（2026-10-12）

状态：**PASS** 是本轮实际成功；**FAIL** 是实际执行失败；**NOT RUN** 是未执行。Phase 1B Real MCP 成功是历史证据，不等于 Phase 2 Real Model 成功。

## 本轮结果

| 项目 | 状态 | 实际证据与限制 |
| --- | --- | --- |
| `origin/main` 与 PR #4 | PASS | `git fetch origin` 后 `origin/main=d58af73c84d8fddaff65de64f5cb629f1e3cb71e`，提交标题含 `(#4)`；干净旧 HEAD 为 `59ec23a`，从 `origin/main` 新建 `codex/phase2-llm-tool-calling`。 |
| Python 依赖/静态检查 | PASS | Host `uv lock --python 3.13`，`uv sync --frozen --python 3.13`，`uv run --frozen --offline ruff check src tests`。新增 `langchain-openai==1.7.0`；没有大规模升级。 |
| Python 离线测试 | PASS | `uv run --frozen --offline pytest -q`：37 项通过（含旧认证、Mock 函数、参数拒绝和新 Fake Model Graph 测试）。Fake 结果只证明控制流与执行边界。 |
| Web | PASS | `pnpm install --frozen-lockfile --offline`、`pnpm lint`（退出 0，现有 18 个 warning）、`pnpm build`（退出 0，现有 Tailwind 模块格式 warning）。Web 源码未改。 |
| Mock/Real Compose 配置 | PASS | CI 占位变量运行 `docker compose -f infra/compose.yaml config --quiet` 与 `--profile real config --quiet`，均退出 0；不需要模型 Key。 |
| Aegra + Mock MCP + SSE | PASS | 独立项目 `kube-triage-phase2-demo`，回环端口 12027/13001，独立两个卷。`up -d --build --wait` 五服务 healthy；API SSE 运行 `pod`、`logs`、跨 Namespace `pods`，State 中分别有 `CrashLoopBackOff`、`database unavailable`、`Namespace denied`。Thread History ≥3；匿名访问 401；`/approve-demo` interrupt/reject resume 成功；审计同时有 success/rejected 且不含测试 API Token。此项为 **LLM_ENABLED=false 的 Mock MCP 固定命令路径**。 |
| Fake Model Tool Calling | PASS | 测试覆盖不同自然语言→不同原生工具、Pod→Event/Log 多轮、同响应两次调用一一配对、工具/回合预算与下一问重置、越权拒绝、错误分类、提示注入执行层拒绝、三类标明 fixture 的证据。**不是 Real Model PASS**。 |
| Real Model + Mock MCP | NOT RUN | 此会话环境没有提供 `LLM_MODEL` 或 `LLM_API_KEY`；没有可验证的实际模型或标准 Tool Calling 服务。未启动带 Key 的 API、未做浏览器 LLM 展示。 |
| Real Model + Real MCP + Kubernetes | NOT RUN | 同上；没有用旧 Phase 1B 的 Real MCP 结果代替本轮真实模型验收。未查询或修改集群。 |
| Phase 2 浏览器 LLM UI | NOT RUN | 无模型配置；Web 构建和独立容器健康只证明前端可启动，不证明模型调用、报告和浏览器交互。 |
| GitHub CI 三个 Job | NOT RUN | 要在 Draft PR 创建后检查 `python`、`web`、`compose` 三项。 |

## 一条已运行的 Fake 诊断轨迹

用户问“为什么一直重启？”；Fake Model 第一轮返回 `pods_get(namespace=kube-triage-demo,name=crashloop-pod)`，第二轮同一 AIMessage 返回 `events_list(namespace=kube-triage-demo)` 与 `pods_log(namespace=kube-triage-demo,name=crashloop-pod,tail=20)`；Graph 产生 ID 为 `pod/event/log` 的三个 ToolMessage。fixture 中 Pod 为 `Running` 但容器 `CrashLoopBackOff`、重启 5 次；Event 为 `Back-off restarting failed container`，日志为 `database unavailable; exiting with code 1`。Fake 最终报告只把数据库不可用写作**可能原因**。ImagePullBackOff 和 OOMKilled 是另两份明确的静态 fixture；所有这些都不是实际集群故障结论。

## 隔离与清理

Host `docker compose ls --format json` 在测试前显示稳定 `kube-triage-agent`（6 服务，配置归属 `/Users/vc/code/kube-triage-agent` 等旧目录）与 `ragflow-lab`（5 服务）。本轮仅以 `docker compose -p kube-triage-phase2-demo -f infra/compose.yaml --env-file .env up -d --build --wait` 启动独立栈。结束时只执行同前缀的 `down`，再精确执行 `docker volume rm kube-triage-phase2-demo_postgres_data kube-triage-phase2-demo_redis_data`，删除本轮临时 `.env`。清理后 `docker compose ls` 仍仅显示原先两个项目在运行；未用全局 prune，未触及集群、其它项目服务或数据卷。`infra/k8s-mcp/config.toml` 仍只读四工具，`reader.yaml` 仍是单 Namespace 读 Role。

## 真实模型最短补测

在独立栈本项目私有 `.env` 填入 `LLM_ENABLED=true`、实际支持标准 Tool Calling 的 `LLM_MODEL`、`LLM_API_KEY`，自托管服务再填 `LLM_BASE_URL`。从 API 容器内部验证 URL/TLS 可达后，使用独立 Compose 项目名和端口启动；在 Agent Chat 提问，记录不含敏感内容的模型名、Tool Call 名称/参数、ToolMessage 来源、耗时、最终报告与 Thread/SSE/History。要测试 Real MCP 时，另确认受限 kubeconfig 尚有效、Compose 归属和本项目 Namespace，不要为测试创建故障 Pod。`LLM_ENABLED=false` 或 Fake 测试不能替代此补测。
