# Phase 2B：Real LLM 独立验收记录（2026-10-12）

**结论：BLOCKED，不能据此进入 Phase 3。** 本轮已经核实配置、隔离部署、37 项离线测试及旧 Mock/审批/Checkpoint 回归；真实模型请求在发出前被自动审批审查拒绝。因此没有供应商响应、`AIMessage.tool_calls`、Real LLM 诊断或本轮 Real Kubernetes 读取证据。`BLOCKED` 不等于模型不支持 Tool Calling，也不等于代码测试失败。

状态定义：`PASS` 为本轮实际验证；`FAIL` 为实际运行但未满足判据；`NOT RUN` 为未执行；`BLOCKED` 为前置条件阻断。任何 Phase 1B 的 Real MCP 结果、Phase 2 的 Fake Model 结果和本轮固定命令回归都不能代替 Real LLM E2E。

## 基线与真实代码连接

`git fetch origin` 后从 `origin/main=09c9ca322142d0629392798eefd334614b73fa6b` 建立 `codex/phase2b-real-llm-validation`，没有复制旧工作树的改动。`server/aegra.json` 注册 `graph_id=agent`，指向 `graph.py:graph`。`graph.py:_route` 在 `llm.enabled()` 为真时进入 `_llm`；`llm.py:chat_model()` 用 `LLM_MODEL`、`LLM_API_KEY` 和可选 `LLM_BASE_URL` 创建 `ChatOpenAI`。`_llm` 从 `mcp_client.py:_allowed_tools` 发现且核对四个原生工具，通过 `bind_tools` 向模型声明，并发送 `prompts.py:SYSTEM_PROMPT` 和 Thread 中的消息。模型若返回 `AIMessage.tool_calls`，`_after_llm` 转到 `_execute_tool`；后者经 `call_tool` / `validate_call` 做白名单、Namespace、参数和预算检查，调用 MCP，并为每个调用写入同 ID 的 `ToolMessage.tool_call_id`。`_after_tools` 在 LLM 模式回到 `_llm`，直到模型给出最终中文回答或达到上限。Aegra 的 Run 通过 SSE 发送 `data:`，Thread State/History 从 Checkpoint 读取消息。`scripts/acceptance.py` 用 `LLM_ENABLED=false` 走 `parse_demo_command`，只验证固定命令路径。

## 验收表

| ID | 验收项 | 状态 | 真实证据（脱敏） |
| --- | --- | --- | --- |
| B01 | 独立 Compose、凭据隔离和其它项目未受影响 | PASS | 独立工作树及 `-p kube-triage-phase2b-demo`；端口 12027/13001；独立网络、Postgres/Redis 卷。仅复制忽略的 0600 `.env`，结束已删除；没有复制 kubeconfig。清理前后稳定项目 6 个容器和 `ragflow-lab` 5 个容器 ID 一致。 |
| B02 | 真实模型生成标准 Tool Calls | BLOCKED | 隔离 API 容器实际 `LLM_ENABLED_TRUE=True`、`MODEL=deepseek-flash`、Key/URL 均已设置、MCP URL 为 Mock。拟从该容器调用 `ChatOpenAI.bind_tools(...).ainvoke(...)` 时，自动审批在出站前拒绝；没有 `AIMessage` 或供应商错误码。 |
| B03 | Real LLM + Mock MCP 工具调用、ToolMessage 配对 | BLOCKED | Gate A 的真实 Tool Calling 未获执行；37 项 Fake Model 测试中的配对不能计入此项。 |
| B04 | 模型基于工具结果形成中文证据诊断 | BLOCKED | 未获得任何真实模型最终回答；`crashloop-pod` 的静态 fixture 只用于旧 Mock 回归。 |
| B05 | Real LLM + Real MCP/Kubernetes 实际读取 | BLOCKED | Gate B 未通过，按先 B 后 C 的要求没有启动 Real MCP、复制 kubeconfig 或查询集群。本轮没有 Kubernetes 读写。 |
| B06 | 浏览器展示 Tool Call、结果、最终回答；SSE/History | BLOCKED | 本轮没有真实模型浏览器 Run。旧固定命令回归实测 `graph_id=agent`、SSE、Thread State/History、重启持久化，不能算 Real LLM UI。 |
| B07 | Namespace/只读/RBAC、越权拒绝 | BLOCKED | `validate_call` 白名单/Namespace/参数拒绝测试 PASS；固定命令对 `default`、`kube-system` 拒绝 PASS；`config.toml` 仍 `read_only=true` 且只启用四工具，`reader.yaml` 仍为单 Namespace Pod/Event/Logs 读 Role。本轮未进入 Real MCP/RBAC 动态复核，组合门槛未全满足。 |
| B08 | pytest/Ruff、旧 Mock/审批/Checkpoint 基本回归 | PASS | `uv run --python 3.13 --frozen --offline pytest -q`：37 passed；Ruff：All checks passed；独立 Compose `config --quiet` PASS；旧验收临时适配到独立项目并在 `LLM_ENABLED=false` 的 API 上全部 PASS，包括 Auth、Mock MCP、越权拒绝、SSE、审批、重启与 History。随后隔离 API 恢复 `LLM_ENABLED=true`。 |
| B09 | 模型轮次、工具次数、耗时、Token/成本（若可得） | BLOCKED | 没有真实模型 Run，故没有可归属的模型轮次、耗时或 Token/成本；代码上限是每轮最多 4 次模型决策、6 次工具执行，不能当作实测用量。 |

## 本轮执行及阻断点

1. 原有 `.env` 只做屏蔽读取：`LLM_ENABLED=true`、模型 `deepseek-flash`、Key/URL 已设置；URL 是 HTTPS 且不是回环地址。未显示 URL、Key、Demo Token 或任何容器 Env 全量。`infra/compose.yaml:api.environment` 明确注入四个 LLM 变量；独立容器内的布尔检查证实配置生效。`NEXT_PUBLIC_API_URL` 在本轮 Web 构建时设为 `http://localhost:12027`。
2. 先用 `uv` 的本机 Python 3.13 与已有缓存运行 37 项测试和 Ruff。未指定 Python 时 `uv` 默认选 3.14，其 `grpcio` 离线缓存缺项；改选仓库先前使用的 3.13 后通过，没有升级或下载本地依赖。
3. `docker compose -p kube-triage-phase2b-demo -f infra/compose.yaml --env-file .env up -d --build --wait` 的五服务均 healthy。Compose 配置只用 `config --quiet`，没有展开打印密钥。
4. 准备从**隔离 API 容器**发送一条无敏感问题以检查标准 Tool Calling。自动审批审查在执行前拒绝，理由是 `SYSTEM_PROMPT`、MCP 工具定义和问题会发到外部 LLM 端点，而现有授权没有明确覆盖这些具体载荷；审查要求不得绕过。因此没有供应商请求、400/401/403/404/429、TLS、超时或 `invalid_tool_calls` 可分类。也没有借用 Fake Model 伪造 PASS。
5. 仅把隔离项目 API 重建为 `LLM_ENABLED=false`，运行旧脚本的临时副本；副本把 `compose.sh` 的日志和重启操作限定为 `kube-triage-phase2b-demo`。21 条输出均为 PASS。随后只重建该 API 为 `LLM_ENABLED=true`，再次确认容器布尔配置。
6. 仅对本轮项目执行 `docker compose ... down`，并在确认 `com.docker.compose.project=kube-triage-phase2b-demo` 后精确删除它的两个卷。已删除临时 `.env` 与脚本。最后 `docker compose ls` 仅剩原有 `kube-triage-agent` 与 `ragflow-lab`；两项目所有容器 ID 与事前一致。没有操作其他 Compose 项目或集群资源。

## 最小轨迹与证据边界

**真实 LLM Agent Trace：BLOCKED，没有产生。** 拒绝发生在供应商调用之前，因此不能填写“模型 Tool Call → MCP ToolMessage → 后续模型决策 → 最终报告”。

本轮实际发生、仅用于 B08 的**固定命令 + Mock MCP** 轨迹为：用户命令 `pods kube-triage-demo` → `_route` 的 `parse_demo_command` 生成 `pods_list_in_namespace(namespace=kube-triage-demo)` → `_execute_tool` 调用 Mock MCP → 带 `static-fixture`/`mock=true` 的 ToolMessage → `_summarize` 输出 fixture 文本。旧验收在同一隔离 API 上还验证 `pod`、`events`、`logs`、越权拒绝、SSE/History。这里的工具选择来自确定性代码，**不是模型决定**，也不描述真实集群状态。

## 后续验收条件

需明确允许把本仓库 `SYSTEM_PROMPT`、四个只读 MCP 工具的名称/参数 Schema 与无敏感测试问题发送到当前 `.env` 配置的 LLM 端点，且允许模型接收 Mock 或本项目受限 Kubernetes 的脱敏工具结果。获得批准后，重新从独立栈执行 Gate A/B，再按顺序做 Gate C；实际记录每次 `AIMessage.tool_calls`、`invalid_tool_calls`、ToolMessage ID 配对、最终结论、SSE/History、耗时与供应商返回的用量。B01–B08 全 PASS 后才可建议进入 Phase 3。
