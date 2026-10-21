# Issue #69：Deep Agents Filesystem / Context Offloading 隔离 Web Demo 设计

> - 需求：[Issue #69](https://github.com/Vc-great/kube-triage-agent/issues/69)（需求范围入口）；相关历史：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)、[P0 Demo PR #66](https://github.com/Vc-great/kube-triage-agent/pull/66)、[P1 State STOP PR #68](https://github.com/Vc-great/kube-triage-agent/pull/68)。
> - 状态：**Proposed / Planning PR**；规划仅写文档，未实施源码、未执行真实模型或 K8s 测试。
> - 基线：2026-10-21 核对 `origin/main=c666fccf36b22aefd1c1c37236ac5ba5ca5d21d4`；实施前需重新 fetch、查最新 PR/Issue。
> - 锁定版本：`deepagents==0.7.28`（`server/pyproject.toml`）、`aegra-cli==0.10.8`，以现有 `uv.lock` 和实际安装 SDK 复核为准。
> - **唯一权威验收矩阵是本文第 6 节**。Issue #69 只指向本文，不复制 Gate。Issue #41 的历史 B3/B5/B8 及 STOP 继续有效；本 Demo PASS 不能重标 #41 为 PASS。
> - 执行授权：本次仅创建纯文档 Planning PR；Planning PR 经用户审阅、合并进 main 后，方可给 AO 执行第 5 节的 S1→S3。用户已明确不将原生 Summarization / Aegra State 写入口封闭作为本 Demo 的前置需求，**不等同于同意打开真实集群或公开服务**。

## 1. 背景、已实现和缺口

用户目标：在现有浏览器 Demo 中真正体验 Deep Agents 原生 Virtual Filesystem 与 Context Offloading，并通过可核对的 Tool Call / State / Checkpoint 证据知道“文件何时写入、何时读取、为何缩短模型上下文”。

当前已实现（不是本计划新增）：
- `server/src/kube_triage/deep_diagnosis.py`：真实 `create_deep_agent`、`StateBackend()`、四个严格 Reader；`HarnessProfile.excluded_tools` 及 `ReaderBoundary` 将文件、Shell、Subagent 等全部挡住；返回证据有 Namespace/UID/Tool ID 检查及 16 KiB 单结果上限。
- `server/src/kube_triage/deep_diagnosis_planning.py`：原生 `TodoListMiddleware`、`write_todos`、`PlanningBoundary`，当前模型工具精确集合为“四 Reader + Todo”；现有预算：10 次模型决策、6 次 Reader、5 次 Todo 写入。
- `server/aegra.phase-b1.json` 和 `make dev-deep-demo`：隔离 Aegra 多 Graph、合成 Mock Reader + 原有真实 LLM 路径、前端 Todo/Tool Timeline/SSE/Thread/Checkpoint，默认正式 `server/aegra.json` 仅有 `agent`。
- `server/tests/test_deep_diagnosis_summary_spike.py` 和 `docs/issue41-p1-summary-spike-validation.md`：证明客户端可从 Aegra `update_thread_state` 更新 `files`，不经 Middleware；原生 Summary S1 BLOCKED，未修复。
- 现有 Reader 每次最多 16 KiB；因此**不能**假设一条工具结果自然超过 Deep Agents 原生默认 20,000 Tokens 离线阈值。

当前尚无：对模型开放的 `write_file/read_file`；可回读的大结果 Offloading 演示；文件与 Todo/Reader 分别计预算；浏览器中可见的文件工具事件。本计划不把“仅传入 StateBackend”写成“Filesystem 已完成”。

## 2. 范围、取舍与已知风险接受

### In Scope

1. 新增**独立 opt-in 的 offload 实验 Graph 和启动 Profile**；不替换 P0 Planning ON/OFF，沿用现有 Web 和合成 Mock Reader 运行链路。
2. 复用锁定 SDK 的 **原生** `FilesystemMiddleware` + `StateBackend`，开放最小工具集合 `ls`、`read_file`、`write_file`、`grep`（最终以 SDK assembled tool list 证明，不自行创建同名替代工具）。
3. **区分两条能力**：
   - A. *Model-managed virtual notes*：LLM 自行调用 `write_file('/notes/...')` 保存非权威诊断笔记，再用 `read_file`/`grep` 回读。
   - B. *SDK automatic tool-result offloading*：当合成 Reader 的某条 `ToolMessage` 超过实验阈值时，由 SDK 自动存入 `/large_tool_results/` 等内部路径；模型看到预览/文件引用，按需 `read_file(offset,limit)` 回读。**该阈值只针对新 Graph 生效**。
4. 以合成 Fixture 测短/长 ToolMessage、Checkpoint 同 Thread 恢复、另一个 Thread 隔离、并发/取消/超时负测；现有 SSE/Timeline 可见 file tools 的调用与返回（不要求独立文件管理页）。
5. 明确记录已知 Aegra State 输入可写入 `files` 的残留缺陷和使用限制，不虚称安全封闭。

### Out of Scope

- 原生 Summarization、现有正式 `context_summary.py`、#41 P1 后续工作；不为本 Demo 修复 Aegra State 注入面。
- 真实 Kubernetes、Repair/HITL、RBAC 扩大、Host FS、`FilesystemBackend`、`LocalShellBackend`、`execute`、`delete`、`edit_file`、`glob`、`task`、StoreBackend、跨 Thread Memory、Skills/多 Agent。
- 不建 CLI、额外 Agent Server、文件上传/下载管理台、新数据库表、独立文件服务，也不跑大规模付费 A/B、开启 Langfuse 额外外传。
- 不提高或取消原有四 Reader 的 Namespace、工具参数校验与 **16 KiB 单次结果限制**；不将虚拟笔记转换成已验证 K8s 事实。

### 明确风险接受（仅本地合成 Demo）

用户允许把 PR #68 所证实的 Aegra `update_thread_state` → `files` 旁路视为本 Demo 的**已知限制**，继续做隔离文件能力演示；**不意味着该旁路不存在或被修复**。必须：
- 仅对合成数据工作；不要在模型、文件、Checkpoint、Trace 写入真实 Secret、kubeconfig、业务日志。
- 仅本机/SSH 本地端口转发的实验 API/Web，不能向公网、共享多用户或稳定环境暴露；不得把端口绑定和 `CORS` 当作完整鉴权。
- State 中的文件、手动笔记、客户端可修改的内容视为 **untrusted**；不能用于绕过 ReaderBoundary 或作当前 UID、K8s 实际状态的权威证据。
- 原 #41 B3 / B5 的安全状态保持 BLOCKED；可通过的是 #69 **隔离 Demo 功能 Gate**，二者不同。
- 如果不能限制在合成 Mock 和隔离服务中，则 **STOP / BLOCKED**，不得在真实 Reader 路径上“先上线再看看”。

## 3. 方案与数据流

~~~mermaid
flowchart TD
    U[Browser / existing Chat UI] --> R[Isolated Aegra Offload Demo Profile]
    R --> G[deep_diagnosis_offload]
    G --> P[Deep Agents: Planning + TodoList]
    P --> B[Execution Boundary: Reader / Todo / FS budgets]
    B --> M[SDK FilesystemMiddleware + StateBackend]
    B --> K[4 Synthetic Mock Reader tools]
    K -->|small ToolMessage| L[Model context: inline result]
    K -->|over demo threshold| O[SDK native large_tool_results offload]
    O --> S[(Thread Checkpoint files)]
    O --> Q[Model context: preview + file path]
    M -->|write_file /notes| S
    Q -->|read_file offset/limit| M
    M -->|read_file / notes| G
    L --> G
    G -->|SSE Tool / Todo / final answer| U
~~~

### 3.1 Graph / Mode / SDK 组装

候选修改范围（AO 以最新 main 与实际源码为准）：
- `server/src/kube_triage/deep_diagnosis_offload.py`：独立图工厂；引用现有 Planning 及 Reader 工具实现，避免复制整套 Graph；由小型配置/扩展复用 `PlanningBoundary`，**不要修改正式 Graph、旧 P0 行为**。
- `server/src/kube_triage/deep_diagnosis_offload_entry.py`：专属 opt-in Demo 入口，遵循现有 real-model + synthetic Mock 的故障关闭路径。
- `server/aegra.phase-p2-offload.json`：独立 Aegra 进程仅注册 offload Graph，避免 P0 的 `register_harness_profile('openai',...)` 排除工具集合并集污染新 Graph。原 `server/aegra.json` 和 `aegra.phase-b1.json` 不变。
- `scripts/dev.py`、`Makefile`：复用 `dev-deep-demo` 的已有进程监管，新增类似 `make dev-deep-offload-demo` 的入口；仅合成 Mock MCP + 原模型配置，不默认激活真实集群/新增云端 Trace。
- `apps/web/`：尽量零修改；如既有 Graph/Todo/Timeline 的 Graph ID 白名单需要更新，仅做最小映射，文件路径显示为普通文本工具事件，不允许从用户端直接编辑 State `files` 的新 UI。
- `server/tests/` 和 `docs/`：专项 FakeModel/SDK 集成/协议负测、中文验收记录、使用说明。

使用 `create_deep_agent(..., backend=StateBackend(), middleware=[FilesystemMiddleware(...), TodoListMiddleware(), <offload boundary>], ...)` 的组装方向。**仅为说明，不是可直接复制的完成代码**：0.7.28 `create_deep_agent` 自带 `FilesystemMiddleware`，自定义同名中间件可能通过 SDK 的原位替换规则生效；AO 必须在锁定环境使用 SDK 对象 introspection 验证实际组装顺序、唯一 FS 实例、Provider Profile 过滤效果。不得在叠加两个 Middleware、隐藏工具未重新出现等情况下继续 Web 集成。

推荐基于 `FilesystemMiddleware(backend=StateBackend(), tools=['ls','read_file','write_file','grep'], tool_token_limit_before_evict=1024)` 做独立实验；必须用实际安装 0.7.28 API 复核形参及阈值；**1,024 是 Demo 实验阈值而不是生产值**。不启动 Summary Middleware：保持新 Graph 显式排除 `SummarizationMiddleware`，用 assembled stack 验证。禁止 `execute` 和任何宿主盘 Backend。

### 3.2 模型与工具执行白名单

新 Graph 的**精确目标工具集合**是四 Reader + `write_todos` + `ls` + `read_file` + `write_file` + `grep`（合计 9）。不允许 `task`、`edit_file`、`delete`、`glob`、`execute`、`shell`、`apply_patch` 或任何 Repair。模型可见工具集合和执行处理必须一致，不能只靠 Prompt 隐藏。

执行预算独立统计，候选上限：每轮模型决策 12、Reader 6、Todo 写入 5、**模型显式文件工具调用合计 8（其中写入最多 4）**；SDK 内部自动 Offloading 不消耗模型文件调用次数，但其失败需要可观察。对多 Tool Calls 同一回合、重复 ID、Call ID 与回执错配、并发文件写入，以执行前验证为准；不可依赖执行后返回 `error` 来撤销已经提交的 State。任一未知文件工具直接拒绝。

文件路径规则：
- 模型写入只允许 `/notes/` 下归一化的相对文件（绝对虚拟路径）；拒绝路径穿越、路径别名和对内部 `/large_tool_results/`、`/conversation_history/` 等路径的模型写入。
- 模型可读取 `/notes/` 与 SDK 自动 Offload 结果所在内部路径；禁止读取未知文件路径、跨 Thread 状态，以及任何宿主机路径。读写路径校验放在**执行层**，优先使用 SDK 公开 `permissions` 与 `FilesystemPermission`（若锁定 SDK 提供）；必要时按现有 Boundary 在 handler 前验证，而非工具执行后拒绝。
- 单条模型写入 `content` 最多建议 8 KiB UTF-8；`read_file` 的 offset/limit 有合理范围（例如 limit ≤100 行），单轮调用计数控制。**不宣称有已经证明的跨并发原子总配额**；如需多轮全 Thread 文件数/总量上限，必须验证预写原子性，否则将其列为残留限制，不静默声明“64 KiB 硬上限”。
- SDK 自动写入内部文件路径不应被模型 `write_file` 覆盖；验证 built-in permission 对 internal offload 的行为，不能让权限限制误阻断 SDK 正常 offload。
- 原始 ToolMessage 和模型调用结果的 `tool_call_id`、`name`、`status` 成对；模型读到的预览/笔记不可作为新的 `pods_get` 成功回执。

### 3.3 Offloading 触发与证据契约

**务必对比两个不同动作：**
- 手动 `write_file`：LLM 主动将分析笔记写入虚拟文件。即使文件写入成功，也不代表 SDK 自动压缩过大工具结果。
- 自动 Offloading：真实 SDK `FilesystemMiddleware` 对某条**合成**长 Reader ToolMessage 根据阈值替换模型可见内容，文件里保存完整原结果；回执出现预览和路径，可通过 SDK `read_file` 分页恢复。

离线场景使用已存在合成 Mock Reader 的真实封装，准备：
1. 小结果（不超过实验阈值）→ 原文内联、无 `large_tool_results` 文件。
2. 长结果（超过 1,024 token 等效阈值，但 **保留原 Reader ≤16 KiB**）→ Native Offload；必须断言路径、消息 preview/引用、完整内容可读性与 Checkpoint 保存，而不是仅检查 `files` 存在。
3. `read_file(offset, limit)` 多次检索完整结果的不同片段。模型最终结论仍以**本轮可信 Reader 证据**为依据；文件回读是低信任缓存，不单独证明实时 Kubernetes 状态。
4. 故障样本：Backend 写失败、读失败、模型重复工具调用、文件缺失/损坏、Thread 切换、断线/取消。故障不能表现为“已经完整读取所有证据”或“确证根因”。

关闭 Summary 后，上下文预算不一定足够应对任意长对话；本功能仅针对**单条大工具结果**的缩减，不承诺历史对话总体无限压缩。应对文件数量增多导致的 Checkpoint 膨胀在 Demo 中明确记录；不引入新持久化组件。

### 3.4 Aegra、State、浏览器与已知旁路

`StateBackend` 只使用本 Thread 的 LangGraph State/Checkpoint 保存虚拟文件，不接触宿主磁盘；同 Thread 后续回合可 `read_file`，不同 Thread 不应自然共享。新建 Graph 与 P0/正式 Graph 分离，旧 Thread 不自动迁移，避免污染现有会话。

**明确限制**：既有 Aegra 外部 `update_thread_state` 可直接注入 `files`，因此在新实验 Graph 中“通过 `read_file` 读到某段 State 内容”不能被宣称为可信/由模型合法写入；本项目只在单用户、合成数据、本地不公开环境验证正常路径的功能特性。保留现有 State 旁路回归用例及失败证据，不修改 Aegra 权限逻辑以制造虚假的 Gate PASS。

前端尽量复用既有 Timeline、Todos、SSE：能看到 `write_file/read_file/grep/ls` 调用和文件路径、自动 Offload 的引用预览，以及重新查询后报告；不要求设计独立 FS 管理 UI。必要时增加只显示合成数据的 `Offloaded` 提示，但不能暴露长文件全文、隐藏内部状态字段或凭据。取消/刷新/重连保证状态展示与 Checkpoint 一致；无法断言原子回滚时不要求人工造回滚结果。

## 4. 方案选择与风险/回退

| 方案 | 优点 | 成本与风险 | 决策 |
| --- | --- | --- | --- |
| A：独立 Graph + 原生 FS Middleware + StateBackend + 小阈值 | 现有技术栈、同 Thread Checkpoint、Web 真实工具轨迹、无宿主磁盘；可精确展示两个概念 | Aegra State 注入旁路仍存在；虚拟文件随 Checkpoint 膨胀 | **推荐，Demo-only** |
| B：直接修改现有 Planning Graph 开放 FS | 文件少 | Profile 排除项可能合并、P0 回归风险、旧会话语义漂移 | 不选 |
| C：FilesystemBackend / LocalShellBackend / 自建文件服务器 | 文件直观易调试 | Web 端带来宿主机读写权限、泄密和清理问题，不适合 Demo | 禁止 |
| D：仅自己写 Prompt 要求短文本，或新建自定义“存文件 Tool” | 实施最简单 | 无法验证 Deep Agents 原生 Offloading | 不选 |

主要风险：State 字段可注入、合成文件被错误当作真实证据、Profile 并集导致 FS 仍被隐藏、原生 Offload 被手工 `write_file` 混淆、取消/并发下的非事务写入、Checkpoint 过大、浏览器泄露内容。

**回退**：不运行 `make dev-deep-offload-demo` / 移除独立 `aegra.phase-p2-offload.json` Graph 即回到 P0；正式 `agent` 和 P0 两 Graph/Checkpoint、Repair/HITL/Memory/SSE 保持不变；不删除共享数据库卷和历史证据。

**STOP**：SDK API 或实际 assembled middleware 与设计假设冲突且无法轻量修正；需要放开主/正式 Graph、接真实 K8s、放宽 Reader、引入 Shell/Host FS 或公开 Aegra；能从其他 Thread 读取到文件；文件回读绕开 ReaderBoundary 导致错误“已验证”结论；敏感数据外传、付费调用超授权、破坏已有 Checkpoint/CI。不得以 Demo 为由消除上述 STOP。

## 5. 阶段实施计划

| 阶段 | 实施范围 | 交付 | 是否能继续 |
| --- | --- | --- | --- |
| **Planning（当前）** | 仅本文与 Issue #69 | 纯文档 PR，Refs #69 | 经用户审阅并合并 main |
| **S1：锁定 SDK / FakeModel PoC** | 新进程隔离 Profile、原生 FS 唯一实例、9 工具清单、1,024 阈值、短/长合成 ToolMessage、路径/回读/Thread 限制 | 专项测试与证据（可在同一实施 PR 逐阶段提交） | Gate F0–F3 PASS 才进 S2 |
| **S2：隔离 Aegra + Web Demo** | 新 Graph + 入口 + Make Profile + 最小 Timeline 映射；只起本任务独立服务和合成 Mock | 可用的 `make dev-deep-offload-demo` + Aegra State/SSE/Checkpoint/浏览器证据 | Gate F4–F6 PASS 才进 S3 |
| **S3：工程收口 / 审查** | Ruff/pytest/Web lint-build/CI、中文手册和残留风险、独立 AO Review | 1 个 Implementation PR（Refs #69），记录 F0–F8 状态 | 用户最后决定合并；未满足最终 Gate 不关闭 Issue |

优先所有行为离线 FakeModel 验证，再用既有可获授权的 Provider 路径做**少量合成 Mock** Smoke；真实模型调用不是进入 S2 的前置条件。若须付费模型做浏览器验证：先取得该轮请求范围/成本明确授权，不能仅依靠现有 .env 中有 Key。不能实时证明调用上限时，真实模型 Smoke 维持 `NOT RUN`。

Worker 按 `AGENTS.md`：fetch 最新 main、独立 Worktree、先验证当前代码和未合并 PR、遵守各阶段 STOP；纯合成数据；先执行较小专项测试再全量回归；每个 Gate 标 PASS / FAIL / NOT RUN / BLOCKED / UNKNOWN 并贴证据，绝不能把 Mock 判作真实 K8s PASS。

## 6. 权威验收 Gate（仅此处维护）

| Gate | 验证对象 / 环境 | PASS 条件与实际证据要求 |
| --- | --- | --- |
| **F0** | 基线/依赖 | 记录实际 `origin/main`、SDK 0.7.28、Aegra 0.10.8、原有 P0/正式 Graph 未变，仓库已无冲突实施 PR；附命令/版本/实际路径 |
| **F1** | 新 Graph 工具/中间件 | assembled stack 仅 1 个原生 `FilesystemMiddleware`，明确未启 Summary；模型工具**恰 9 个**，Shell/Repair/task/delete/edit/glob 不可见且执行拒绝；P0 严格旧名单保留；附 FakeModel 捕获 |
| **F2** | 原生虚拟文件工具 | `write_file('/notes/...')` 写入，`ls/read_file/grep` 可读取 SDK `StateBackend` 实际文件；未知路径/穿越/内部目录模型写入/过大内容/超预算在写入**前**拒绝，拒绝后无文件增量；模型回执 ID 成对 |
| **F3** | **自动** Offloading | 在保持 Reader ≤16 KiB 下，短结果不创建 Offload；超过实验阈值的合成 Reader 结果**由 SDK 自动**写入内部 large_tool_results、ToolMessage 有路径+预览，`read_file(offset,limit)` 可恢复原结果不同片段，模型输入相较全量原文确实变短；不得用模型主动 `write_file` 冒充 |
| **F4** | State/Thread/失效 | 同 Thread Checkpoint 可续读；新 Thread 读不到前一个 Thread 笔记或 Offload；Backend 写/读失败、取消/超时不得显示“证据完整”或“诊断已证实”；取消不假称原子回滚；附 State/Tool ID/Checkpoint 测试 |
| **F5** | 隔离和回归 | 新 Demo 只用合成 Mock，所有未知 FS/Host FS/Shell/Repair/K8s 越权拒绝；正式 + P0 行为、Reader Namespace/UID/16KiB、HITL/Memory/SSE 不回归；#41 Aegra State 旁路仍标为**未修复**，不得将其变为安全 PASS |
| **F6** | Web / Aegra | 新 Profile 可用独立启动/停止，页面展示 Planning Todo、四 Reader、虚拟 FS 调用、自动引用及最终报告；可检查 Aegra SSE、Thread 切换/刷新/重连；明确展示或记录本地合成数据限制；浏览器真人未执行须为 NOT RUN |
| **F7** | 工程 | `uv run --frozen ruff check src tests`、`uv run --frozen pytest -q`、涉及前端则 `pnpm lint && pnpm build`、相关 CI、`git diff --check`；每一项附真实日志/HEAD/CI 链接，环境限制区分 FAIL 与 BLOCKED |
| **F8** | 交付与披露 | Implementation PR `Refs #69`、中文使用/验收文档、演示关闭方式、Backend/阈值/费用/局限说明、独立审查记录；不声称生产安全/真实 Kubernetes 测试，用户批准前不合并、不提前关闭 #69 |

Gate **F0–F3** 是进入 Web 集成的强制前置；F4/F5 对发现跨 Thread 泄露、宿主机工具出现等异常属于阻断条件；F6/F7/F8 最终以实际适用情况判定。不能使用 `NOT RUN` 代替核心路径的 F3 PASS。

特别说明：**F5 是这次“合成隔离 Demo 的权限/回归” Gate，不是解决 #41 原 B3 的 State API 防伪安全 Gate**。新文件的来源可信度受已知外部 State 更新路径影响，不能作为最终 Kubernetes 可信证据。

## 7. SDK/社区依据与实施时再验证

官方文档（会随最新版本变动，**必须用锁定 wheel 交叉验证**）：
- [Deep Agents Backends](https://docs.langchain.com/oss/python/deepagents/backends)：`StateBackend` 的 Thread/Checkpoint 存储；官方不建议 Web API 使用直接访问宿主机的 `FilesystemBackend`。
- [Context engineering / Offloading](https://docs.langchain.com/oss/python/deepagents/context-engineering)：大工具结果的原生自动 Offloading、预览/引用/按需读取；官方默认阈值约 20,000 Tokens，不适合本 Demo 的 Reader 上限。
- [Harness Profiles](https://docs.langchain.com/oss/python/deepagents/profiles)：`excluded_tools`、`excluded_middleware` 合并为并集；新 Graph 要实际探测并尽量进程隔离。

锁定源码（2026-10-21 已通过 GitHub ref 核对）：
- [0.7.28 FilesystemMiddleware](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/middleware/filesystem.py)：构造器含 `tools`、`tool_token_limit_before_evict: int|None = 20000`、`backend` 等；`read_file` 必须在 `tools` 中；自动对大工具结果 Offload。
- [0.7.28 create_deep_agent](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/graph.py)：已有 FilesystemMiddleware 和 Summary scaffolding，custom middleware/profile 的实际实例替换顺序由实施前实测确认。
- [本仓库原生摘要 STOP 证据](../issue41-p1-summary-spike-validation.md)：Aegra `files` 写入旁路与历史相关测试不可删除、不得更改结论。

## 8. 记录与 AO 交接

### 规划/实施记录

- 2026-10-21：从 #41 可选 P2 单独提出 #69，明确 Demo-only 风险接受；已验证锁定 SDK API 存在，未运行本需求测试。规划 PR 仅文档。
- 后续 S1/S2/S3 各阶段记录实际 SHA、测试命令、环境、请求次数、结果及设计偏差。**未实测项目不得预填 PASS**。

### AO 短提示词（仅规划 PR 合并 main 后有效）

> 实施 `Vc-great/kube-triage-agent` Issue #69 的 S1→S3（必须逐 Gate 通过再继续）。先 fetch 最新 main，从独立 Worktree 读取 `AGENTS.md`、Issue #69 和 `docs/plans/issue-69-deepagents-filesystem-offloading-demo.md`。严格复用锁定 Deep Agents 0.7.28 原生 FilesystemMiddleware+StateBackend、合成 Mock+Web，不做 Summary/CLI/Host FS/Shell/Repair/真实 K8s。先完成 F0–F3 FakeModel SDK PoC；PASS 后进入 Aegra/Web，再完成 F4–F8。保留 #41 Aegra `files` 旁路未修复记录，不把 Demo PASS 写成生产安全。需要扩大权限/外联/调用付费模型、破坏正式链路、跨 Thread 泄露或 SDK 假设不成立时 STOP。提交独立 Implementation PR（Refs #69），附逐 Gate 证据和中文报告；未经用户批准不合并、不关闭 Issue。
