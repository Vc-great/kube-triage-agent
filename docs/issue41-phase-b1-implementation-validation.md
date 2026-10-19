# Issue #41 Phase B1 Implementation 验收记录

## 基线与范围

- Issue：[#41](https://github.com/Vc-great/kube-triage-agent/issues/41)，实施时保持 Open。
- 批准设计：[Phase B1 Planning 设计](plans/issue-41-deep-agents-phase-b1.md)；规划 PR [#45](https://github.com/Vc-great/kube-triage-agent/pull/45) 已合并。
- 实施基线：`origin/main=27e2a6913c481fc344b0d17a057bb1f04a39a597`（与 PR #45 merge commit 一致）。实施分支从该 SHA 创建。
- 锁定依赖：Python 3.14.6、Aegra 0.10.8、Deep Agents 0.7.28、LangGraph 1.2.14、langchain-core 1.6.12；Web Node 24.20.0、pnpm 10.5.1、Next.js 16.3.8。
- 范围：保留正式 `agent` 和 Phase A `deep_diagnosis`；新增隔离 `deep_diagnosis_planning`，仅实现 B1。无 B2/B3 实施。
- 安全：仅 FakeModel、合成 Mock MCP 和 localhost Aegra；无真实 Provider/Kubernetes、无 OTel/Langfuse 外传。测试资源已按本次 AO session 归属停止并删除。

## 实现与契约偏差

新增 `TodoListMiddleware` 显式提供的 SDK `write_todos` / `PlanningState.todos`，没有手写 Todo 状态。Planning Graph 只允许模型看到四个 Reader 加一个本地 `write_todos`；执行时再次验证名称、Tool Call ID、Todo 项/状态/长度和独立预算。Reader 继续通过 Phase A `call_tool()`，沿用 Namespace、参数、原生 MCP `tools/list`、8 秒超时和 16 KiB 截断。

隔离 Aegra 联调发现：Phase A 与 Planning Graph 使用同一个 SDK provider HarnessProfile 时，profile 的 `excluded_tools` 会取并集，导致 Phase A 的 `write_todos` 排除项也屏蔽 Planning Middleware 的工具。修复仅从 Phase A Profile 元数据中移除对当前未注入工具的冗余 `write_todos` 排除；Phase A 仍只向模型提供四 Reader，`ReaderBoundary` 仍拒绝所有非 Reader。基线和 Planning 两张图在同一个 Aegra 配置中的实测均证明该边界。SDK `TodoListMiddleware` 返回 `Command` 并更新 `todos`；边界已验证 Command 中的状态内容及 Tool ID 后才接受更新。

## Issue #41 Phase B Gate

| Gate | 状态 | B1 证据与限制 |
| --- | --- | --- |
| **B1 简单/复杂任务** | **PASS** | FakeModel 单测覆盖问候直答、复杂计划建立/更新、Aegra values SSE 中 Todo 状态。简单任务未强制写 Todo。 |
| **B2 Replanning / 预算** | **PASS** | 合成 Reader 403 后计划保留未完成并安全报告；Reader 6 次边界、并行第 7 次同 ID 错误、Todo 第 6 次拒绝、10 次模型决策上限和 Aegra `interrupted` 取消均有测试。Provider 内部重试没有发生，未将其混同模型决策。 |
| **B3 Filesystem 隔离** | **NOT RUN** | B2 虚拟文件功能不在本阶段。当前模型工具集无文件/Shell/`task` 工具，未知执行名被拒；完整虚拟路径/权限/删除测试留待获批阶段。 |
| **B4 Context 协议** | **NOT RUN** | 不实施 Offloading/Summarization。Phase A 消息/证据和历史 Checkpoint 未改；本轮只验证 B1 Todo State 和新轮次重置。 |
| **B5 安全与记忆** | **PASS（B1 范围）** | FakeModel 覆盖跨 Namespace、预置 AI/Tool 伪造、恶意日志、同名不同 UID；Reader 证据守卫复用 Phase A。Memory/HITL/Repair 源码未改且全套回归通过。真实 LLM 注入语义为 NOT RUN。 |
| **B6 UI / Trace** | **PASS（本机范围）** | Aegra 0.10.8 的 Planning Graph SSE `values`、Todo Checkpoint/新轮清空、Last-Event-ID 续流与取消已测；React 只在 Planning Graph 校验后显示合法 Todo；Web lint/build 通过。真实浏览器手工验收和 Langfuse Cloud 可见性 NOT RUN。 |
| **B7 离线 A/B** | **PASS（协议/开销计数）** | 无 Provider FakeModel + 同源合成 Reader 回执，覆盖 CrashLoop、ImagePull、OOM、Healthy 与两项复杂合成案的 OFF/ON 配对。所有场景 Reader 次数相同；简单案 OFF/ON 模型决策均为 2、Todo 为 0；复杂案 OFF 为 2 次决策/0 Todo，ON 为 4 次决策/2 Todo。固定 Fake 回答不是质量评分，也不能推断真实 Token、时延或诊断准确率。 |
| **B8 Real LLM + Mock MCP** | **NOT RUN** | 未获授权，且本次明确禁止真实付费 Provider/外传。Token Usage 与真实模型质量收益 UNKNOWN。 |
| **B9 回归与交付** | **IN PROGRESS** | Python/Web 本地 Gate 已完成；Draft PR、CI 和独立 Reviewer 结果待记录。PR 将只引用 `Refs #41`，不自动合并、不关闭 Issue。 |

## 实际命令与证据

Python 使用锁定依赖环境：

```text
server/.venv/bin/ruff check server/src server/tests
server/.venv/bin/pytest -q server/tests
```

结果：Ruff `All checks passed!`；pytest `438 passed`。

Web 使用 `pnpm install --frozen-lockfile --offline --ignore-scripts` 从本机 store 复用 647 个锁定包，下载 0 个包；随后：

```text
pnpm lint
pnpm build
```

结果：lint exit 0（18 条仓库既有 warning、0 error；新增 Todo 组件无 lint warning）；Next.js production build 成功。

隔离协议命令：`python scripts/issue41_phase_b1_smoke.py`。测试 Aegra 0.10.8 同时加载 `deep_diagnosis` 与 `deep_diagnosis_planning`，FakeModel 通过合成 Mock MCP 跑复杂调查和简单问候；验证工具 ID 配对、结构化 Todo SSE、中断恢复（Last-Event-ID 不重放）、新轮次清空、baseline 仅 Reader，以及取消状态 `interrupted`。Aegra 使用本地专属 Postgres/Redis 端口与卷，OTel 关闭；结束后精确清理了本次资源。

早期 Phase A A08=**FAIL** 与 Phase 3B B06=**FAIL** 原样保留。本报告不覆盖、不重评分历史结论。

## 成本、缺口与回退

- Mock 配对只测协议与调用数：复杂 Planning ON 比 OFF 多 2 次模型决策和 2 次本地 Todo 调用；简单场景没有 Planning 额外调用。Provider Usage 缺失，真实 Token/费用、延迟和质量收益均 UNKNOWN / NOT RUN。
- 外部 Provider 的自动重试未测。Langfuse Cloud、真实 Reader、真实 Kubernetes、浏览器手工检查均未运行。
- 回退时不改正式 `agent`；从 `server/aegra.phase-b1.json` 移除 `deep_diagnosis_planning` 入口或不加载该实验配置即可回到现有路径。不会迁移/删除旧 Thread、Checkpoint、Golden，也不变更 Repair/HITL/Memory。
