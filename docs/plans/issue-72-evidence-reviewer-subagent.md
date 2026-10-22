# Issue #72：Evidence Reviewer Subagent — 需求、架构与实施 Gate

> - 需求：[Issue #72](https://github.com/Vc-great/kube-triage-agent/issues/72)；相关 [Deep Agents Core Demo PR #66](https://github.com/Vc-great/kube-triage-agent/pull/66)、[Issue #69](https://github.com/Vc-great/kube-triage-agent/issues/69)、[Filesystem 文档 PR #70](https://github.com/Vc-great/kube-triage-agent/pull/70) 与 [#71](https://github.com/Vc-great/kube-triage-agent/pull/71)。
> - 状态：**Proposed / Planning PR**；此文是拟议设计，绝非已完成的代码或测试报告。
> - 规划基线：2026-10-22 核实 GitHub `main=0757cfc70103868843b5cac81af836aa8428724a`（PR #71 为文档）；开发前重 fetch 并检查其他工作树/PR。
> - 锁定依赖：`deepagents==0.7.28`、`aegra-cli==0.10.8`（`server/pyproject.toml`），禁止为本任务直接升级 SDK。
> - **状态差异**：用户报告“Filesystem 代码已经合并”；本次 GitHub 查询未发现 #69 Implementation PR，main 没有 `server/src/kube_triage/deep_diagnosis_offload.py`，#69 仍 Open。仅确认 #70/#71 规划文档已合并；本需求独立基于已合并的 P0 Planning Graph，因此可以开展独立规划，无需将 #69 视为前置，但实施前要再次核对、避免重复或冲突。
> - **唯一权威验收标准**：本文第 6 节 Gate R0–R9；Issue #72 只链接本文，不维护第二套矩阵。
> - 当前授权：仅写入规划文档并创建 Planning PR；**须先审阅、合并规划 PR 才能运行 AO 实施**。真实付费模型调用和真实 Kubernetes 出站不包含在本次默认授权。

## 1. 背景与当前实现

### 为什么需要

现有 Deep Agents Planning Graph 能以真实 Tool Calling 读取 Pod、Event、Log、维护 Todo 和提出结论，但候选根因可能引用历史证据、混用 UID、把旧 Event 解释为当前状态或在 403/Timeout 后声称诊断成功。增加一个**证据审查角色**，让主 Agent 保持取证职责，同时用次级 LLM 从独立上下文检查“候选结论是否受到当前证据支持”。

核心工程验证：原生 **Subagent `task` 委派 + 上下文隔离 + 严格零工具执行权限 + 结构化证据审查 + 未复核时的可靠降级**，而不是“两个 Agent 自由聊天”。

### 已有能力（复用，不重复开发）

- `server/src/kube_triage/deep_diagnosis_planning.py`：`create_deep_agent`、`TodoListMiddleware`、`PlanningBoundary`；模型只看到四 Reader + `write_todos`，当前决策、Reader、Todo 独立预算，检查 `ToolMessage` 成对和 Reader Envelope。
- `server/src/kube_triage/deep_diagnosis.py`：原四 Reader schema、`ReaderBoundary`、当前轮 `pods_get` 的 `tool_call_id` / UID 等结构化核验。
- `server/aegra.phase-b1.json`、`server/src/kube_triage/deep_diagnosis_planning_entry.py`、`scripts/dev.py`、`Makefile`、`apps/web/`：现有实验 Graph、Mock Reader / FakeModel、Aegra Thread/Run/SSE/Checkpoint、Todo 和工具时间线、`make dev-deep-demo`。
- 正式 `server/aegra.json` 仅注册 `agent`；现有 HITL / Repair / Incident Memory 属于正式路径，不在本任务重做。
- #41 P1 Summary 已知 Aegra 客户端可注入 `files` 的 State 旁路；Reviewer **不能**把来自 File State 的文本当成不可伪造来源。#69 的分页 Offload 实现未在本次可读取 main 上确认。

### 锁定 SDK 0.7.28 的关键事实

1. `create_deep_agent(subagents=[...])` 支持声明式 `SubAgent`（`name`、`description`、`system_prompt`、`tools`、`model`、`middleware`、`mode` 等）和 `CompiledSubAgent`。有同步子代理时由原生 `SubAgentMiddleware` 注入 `task(description,subagent_type)`；无同步子代理则不注入。
2. 默认 `general-purpose` 子代理可能自动添加；必须明确用 `GeneralPurposeSubagentProfile(enabled=False)` 关闭，只允许 `evidence-reviewer` 一名。
3. `tools=[]` 仅清空显式继承工具，声明式子代理仍会自动配置 `FilesystemMiddleware`；要同时用子代理层的工具白名单/排除配置与真实 assembled tool list 证明确实无 `read_file/write_file/ls/grep/execute`、无 Reader 和 `task`。
4. 默认 isolated 子代理获得 `task.description` 作为新的唯一 HumanMessage，但 SDK 实现仍向其传递部分父 State（排除 messages/todos/structured_response 等键，不自动排除普通 `files`）；**isolated context 不等于完全 State 隔离或额外安全边界**。必须实测不泄露、不回写意外共享 State；若有不可接受的泄露路径应考虑 `CompiledSubAgent` 的最小 State Schema（需独立设计审阅，不能随意扩大实施）。
5. `task` 结果是与父 `tool_call_id` 配对的 ToolMessage/Command；SDK 可能向主 State 合并非排除字段。需要完整检验返回值与 State delta，而不是仅依赖 `task` 输出的“PASS”文本。
6. 在同进程多次 `register_harness_profile` 时 `excluded_tools` 取并集；旧 P0 的 `_HIDDEN` 含 `task`。本任务使用**独立 Aegra 进程/Profile**，并在 FakeModel 下检查 `task` 实际被暴露且 P0 工具名单不变。

依据：固定版本源码 [graph.py](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/graph.py) / [subagents.py](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/middleware/subagents.py)；官方 [Subagents 文档](https://docs.langchain.com/oss/python/deepagents/subagents) / [Profiles](https://docs.langchain.com/oss/python/deepagents/profiles)。官网后续 API 可变，实施始终以 lock 版本为准。

## 2. 目标、非目标、安全边界

### In scope

1. 新增独立 opt-in `deep_diagnosis_review` 实验 Graph，保留原四 Reader、Planning Todo 与边界；新增 SDK 原生单个 `evidence-reviewer`、`task`，不变更正式 Graph 或已合并 P0。
2. 对**具备候选诊断结论和本轮来源引用**的复杂诊断进行显式证据复核。简单问候/无诊断目标不强制委派；其他场景 Reviewer 未执行或失败时必须显示 `UNREVIEWED/UNKNOWN`，不得自称完成复核。
3. 有界证据包与声明式审查输出：本轮有效 Tool Call ID、名称、Namespace、Pod/UID、取证时间语义、成功/失败及有限原文片段/哈希；允许 `SUPPORTS` / `CONTRADICTS` / `INSUFFICIENT` / `UNKNOWN`，但不以 LLM 结论替代代码证明。
4. 提供工具、模型决策、单次 task、超时、输出大小和失败预算；FakeModel 合成离线测试、Aegra/Web 工具时间线/Thread 测试及小型 A/B 证据评价。
5. 后续可选择少量真实模型 + 合成 Reader Smoke，须额外明确成本和请求次数授权；本设计阶段不调用。

### Out of scope

- 不依赖 #69 Filesystem 成功或 Summary 恢复；不启用 Skills/Memory/Host FS/Shell/StoreBackend/动态或异步 Subagent/多 reviewer/Supervisor 调度器。
- Reviewer 不查 K8s、不访问 MCP、不执行 Repair、不写任何文件、不持久存储“审查通过”作为原始证据；不更改 Namespace/RBAC。
- 不在正式 Graph 插入强制 Reviewer 审批 Gate，不修改生产 Repair/HITL、现有 Checkpoint 序列化或旧 Thread 数据。
- 不声称 FakeModel 审查证明真实 LLM 质量更好，不以“审查了”充当根因正确率提升；不做 100+ 次付费评测。

### 安全不变量

- 以 **Host 侧确定性验证**定义“本轮真实可用证据”；LLM 的候选结论、Reviewer 文本、State 文件内容均属非权威输入。带 `ToolMessage` 的可信来源仍需通过配对、Envelope、目标 UID 和时序检查。
- 不把 `SUBAGENT=SUPPORTS` 升格为“已证实根因”；Reviewer 为咨询性意见，发现矛盾或未复核时必须标注未确认。
- Reviewer 不能拥有任何可执行工具，包括默认 FS 工具；主 Agent 精确工具集只允许四 Reader、`write_todos` 和原生 `task` 共六个。
- 只使用合成 Mock Reader 数据演示，禁止外联真实集群与写操作；密钥和真实敏感证据禁止进入 Run、日志、Trace、仓库文件。
- Reviewer 不是可信审批者，不拥有更高身份/授权。已有 Aegra State 写入口旁路保持为**已知风险**，本任务不宣称已封闭。

## 3. 架构、模块与契约

### 3.1 图与调用路径

~~~mermaid
flowchart TD
  U[Browser / Mock diagnosis request] --> D[Isolated Aegra deep_diagnosis_review]
  D --> A[Main create_deep_agent: Todo + Reader]
  A --> K[Four bounded synthetic Reader tools]
  K --> E[Host validated current-turn evidence]
  E --> C[Candidate diagnosis / bounded cited claims]
  C --> T{Native task: evidence-reviewer}
  T -->|invoked once| R[Isolated reviewer LLM, no tools]
  T -->|not invoked / failure| N[UNREVIEWED / UNKNOWN]
  R --> V[Schema & citation consistency checks]
  V --> F[Observation / inference / unknown + review status]
  N --> F
  F --> S[SSE + Tool Timeline + final Chinese response]
~~~

**主线推荐**：保持主 Agent 自主 Tool Calling；对明确诊断请求，提示其在已有本轮 Reader 证据后使用原生 `task` 委派一次 `evidence-reviewer`。对于无证据、不需要诊断的简单对话可以直接结束；对于应审查但没有有效 task 结果的诊断，最终文本必须由确定性 Boundary 标记 `UNREVIEWED` 并避免“复核通过”的字样。不为达到演示效果硬塞人工假 `task` 调用。

**强约束事实来源**：`task(description)` 由主模型撰写，因此其中的证据字符串**不能直接被认定为真实 Reader 证据**。优先在主 Agent 的 Task 执行边界构建受信证据摘要（只来自本轮已校验回执），并将其有界附加/替换到原生 `task.description` 中；保留候选结论为 *untrusted claim*。必须先 Spike 验证当前 SDK `ToolCallRequest` 是否支持执行前安全覆写 args 且 `tool_call_id` 不变；如不支持，则采用“模型自述审查 + 最终独立确定性验证”的低保证 Demo，并**显式标注 Reviewer 输入未经绑定来源**，不得声称 R3 强证据绑定 PASS。未批准更改权威 Gate 前，R3 BLOCKED 并 STOP，不做生产性质的伪安全保证。

**审查前准入**：必须出现本轮有效 `pods_get` 或其它已配对成功 Reader/有效失败回执；纯伪造 AI/Tool 历史、未来/其他 Thread 文件、无任何可用来源时禁止标记 `review_verified`。Reader 取证错误（403/404/timeout）可作为“证据不足”材料，但不是健康/根因证据。

### 3.2 实施代码范围（实际文件位置在 S1 复核后确定）

- 推荐新建 `server/src/kube_triage/deep_diagnosis_review.py`，复用 `deep_diagnosis_planning` 的现有 Reader/Todo 逻辑，以额外 ReviewBoundary 扩展执行白名单/预算。若需最小参数化已有 `PlanningBoundary`，必须默认保持原工具列表 5 项不变；禁止复制大量代码并改变 P0。
- 独立 Aegra Entry：`deep_diagnosis_review_entry.py`、实验配置 `server/aegra.phase-review.json`；`TRIAGE_ENV=test` 下 FakeModel/合成 Mock 的显式开关；正式默认配置 `server/aegra.json` 不注册。
- `scripts/dev.py` 与 `Makefile` 只做新 `make dev-deep-review-demo` 的 opt-in 本地 Profile，复用现有 `deep-demo` 环境保护和端口/生命周期监管。只有明确获批准的 Provider Mock Smoke 才启用真实模型。
- Web 复用现有 Timeline/Todo/SSE，最小化展示 reviewer `task`、review status 和引用信息；没有可验证的 streaming 子代理详情则仅显示父 task 状态，不展示虚构的子代理思考。
- `server/tests/` 新增专项规则、FakeModel、Checkpoint、Aegra 和模型输入验证；中文文档收录使用方法、运行成本、Gate 证据。

### 3.3 SubAgent 最小权限配置

`subagents=[{"name":"evidence-reviewer","description":"核查候选诊断与已提供本轮证据的对应关系；不执行取证或修复","system_prompt":"...","tools":[],"model":...}]`，明确使用默认 isolated mode，禁 general-purpose，禁递归任务。

注意：根据锁定 SDK，`tools=[]` **不会移除默认 FilesystemMiddleware 注入的工具**。必须显式配置子代理的工具过滤（例如同一隔离进程中 Profile 的 `excluded_tools` 覆盖所有 FS 工具，但**不排除父 `task`**），并用 FakeModel 实际模型入参确认 Reviewer **工具名单为空**；父 Graph 模型工具必须恰好六项。不能把 Prompt “禁止调用工具”当作执行层安全。

SubAgent 的 isolated 输入虽只保留委派 HumanMessage，但 SDK 可能携带父 State 的普通 `files`；若实测存在跨 Thread 读取、文件修改、未经验证 State 影响输出，则 R2/R5 FAIL、STOP，不能因为选择 mode=isolated 就宣称强隔离。不要启用 `mode='fork'`。

### 3.4 证据契约和审查输出

由 Host 在 Task 前构造**有限 JSON EvidenceManifest**，不是模型自主声明的已验真内容。建议字段（可调整名称但不可改变语义）：

~~~json
{
  "scope": {"namespace": "kube-triage-demo", "thread_id": "<synthetic>", "turn_id": "<synthetic>"},
  "candidate_claim": {"text": "当前容器重启与 OOMKilled 有关", "trusted": false},
  "evidence": [
    {"source_tool_call_id": "call-123", "tool": "pods_get", "status": "success",
     "target": "pod-a", "pod_uid": "fixture-uid-a", "excerpt": "lastState.terminated.reason: OOMKilled",
     "source_hash": "sha256:...", "current_turn": true}
  ],
  "incomplete": false
}
~~~

Manifest 只从本轮 `AIMessage.tool_calls` + 唯一同 ID `ToolMessage` 的实际结果产生；解析失败/缺 UID/旧 UID/不同 Namespace/同 ID 冲突/Reader Error 时保留失败和不确定性，不能补造字段。限制证据条目、描述字符、摘录总量（例如总 ≤8 KiB）；若超预算，显式 `incomplete=true`，Reviewer 不能视为全量证据。

Reviewer 期望产生可解析的**单个、简洁 JSON 对象**，建议：

~~~json
{
  "verdict": "INSUFFICIENT",
  "supported_claims": [],
  "contradictions": [],
  "evidence_refs": ["call-123"],
  "unknowns": ["缺少本轮内存限制和资源用量"],
  "recommended_next_read": "可考虑进一步核对事件",
  "reason": "当前数据不足以将 OOMKilled 确认为唯一根因"
}
~~~

枚举 `SUPPORTS|CONTRADICTS|INSUFFICIENT|UNKNOWN`；限制项数量、长度和引用 ID 只能来自 Manifest。响应不是 SDK `ToolMessage.status` 本身的成功依据，而需通过 Host schema / 引用校验。JSON 不合法、引用不存在、内容注入、超时或失败 → `UNKNOWN / UNREVIEWED`，不能把错误字符串解析成 PASS。

**最终回复规则**：观察/推断/未知严格分开；Reviewer 提供的是第二意见，不能创造未查询的 UID、指标、根因；支持意见不可覆盖 Host 确定性不信任的证据。需要明确区分 `review_status=COMPLETED|SKIPPED|FAILED|UNREVIEWED` 与证据审查 verdict，不能把两个状态混成一个“success”。

### 3.5 预算、失效、Checkpoint 与 UI

建议新 Graph 单轮父模型决策最多 12 次、Reader 6 次、Todo 写入 5 次、**task 1 次**；Reviewer 最多 2 次模型决策、无任何工具，输出和输入字数有限。引入 Reviewer 后耗时/Token 增大是正常预期；优先将 Reviewer 单次执行总时限设为 20 秒实验值，主 Run 的总超时采用项目现有配置，须实测可执行熔断/取消传播，不以 Prompt 约束取代框架保护。上述数值仅限 opt-in Graph，不影响 P0。

禁止同回合混杂并行 task + Reader，禁止多 `task`、未知 `subagent_type`、重复/空 Tool Call ID；父 task 的结果必须按原 ID 回填且不得包含意外修改父 State 的 `files`、`todos`、Reader 证据、Memory 字段。检查取消中尚在执行的子代理不会静默在后台继续访问资源；无法证明的项注明 NOT RUN/BLOCKED。

Thread/Checkpoint：review 仅作用于当前轮，旧 Review 不能跨轮充作当前 verdict；新 Thread 不继承 review，Refresh/Resume 不能重复执行已经完成的 task 或发生二次收费（如 SDK 无法保证，要保留明确限制和 STOP）；不改旧 Checkpoint schema。不存储完整私有推理轨迹，必要时仅保存非敏感合成证据摘要。

Aegra SSE/Web：父工具 Timeline 可显示 `task(evidence-reviewer)` Running/Done/Failed，Task 消息、审查状态和最终答复一致；模型的隐藏 Chain-of-Thought 不做展示要求；浏览器未实测的 UI 状态记 NOT RUN。

## 4. 方案权衡、风险、回退与 STOP

| 方案 | 优点 | 代价 | 决策 |
| --- | --- | --- | --- |
| **A. 原生声明式 SubAgent + 隔离 Graph + Host 证据绑定** | SDK 原生 task、多角色职责清晰、最小新抽象，适合 Demo | 需处理 FS 默认工具、State 传播、任务输入真实性；额外 LLM 成本 | **主方案（先 Spike）** |
| B. 完全自建 LangGraph `review` Node | 状态/权限强控制、无需 task | 偏离学习原生 Deep Agents Subagent 目标；重复工作流逻辑 | 不选 |
| C. General-purpose subagent 直接给四 Reader | 开发快、可自主复查 | 重复 MCP、权限和调用成本扩大，容易产生漂移 | 不选 |
| D. 独立 CompiledSubAgent + 极简 State | 最强结构化边界 | 更多代码、须验证 SDK 返回协议；仅在 A 明确证明不能满足边界时独立审阅 | 后备，不自动切换 |

重点风险：主 Agent 伪造/截断证据、子代理默认 FS 权限、未预期 State delta、额外付费调用、Reviewer 和主 Agent 互相强化幻觉、无有效审查却显示通过、缓存旧诊断与当前 UID 混淆。

**回退**：关闭/不启动新 `deep_diagnosis_review` 的 opt-in Profile，原 `deep_diagnosis_planning`、正式 `agent`、Memory/HITL/Repair 继续正常运行；只清理本任务独立创建的服务/端口，不删共享数据卷或历史 Thread。

**STOP / 重新设计**：无法确证子代理零工具权限；`task` 能访问真实 Reader、Host FS、Shell、Repair；无可靠机制将审查证据限制为当前轮有效来源却想把它当作权威；跨 Thread 污染/未经许可文件写入；更改正式 Graph、旧 Checkpoint/HITL 语义；需要扩大费用/真实 Kubernetes 权限；固定 SDK API 不支持选定关键契约且无法小改满足时。不得自行降低 Gate，保留原失败证据。

## 5. 分阶段实施与独立交付

| 阶段 | 工作 | Gate | 交付 |
| --- | --- | --- | --- |
| **Planning（当前）** | Issue + 本 Markdown + 文档 PR | 人工审阅、合并 main | 纯文档，非实现 |
| **S1：SDK 安全/证据 PoC** | 锁定 wheel、FakeModel、单个原生 Subagent、tool allowlist、当前轮证据绑定、review 输出 schema、负测 | **R0–R4 PASS** | 专项测试与实测报告；失败 STOP |
| **S2：独立 Aegra + Web** | 仅独立合成 Demo 图、入口、Supervisor、小 UI 适配、SSE、Checkpoint、取消/新 Thread | **R5–R7 PASS** | 新 opt-in Demo 和测试；失败 STOP |
| **S3：收口与效果/成本对照** | 6–8 条冻结合成案例，FakeModel/同输入 ON/OFF 主观+客观检查；预算、测试、CI、审查、文档 | **R8–R9 PASS** | 独立 Implementation PR（Refs #72）；由用户决定合并 |

默认 FakeModel/Mock 验证，不批量调用真实模型。若希望证明 Reviewer 在真实 LLM 下能实际改善结论，请用户单独批准明确次数、限额、数据、模型端点；未批准标 `NOT RUN`。**不要用 FakeModel 对照自称真实诊断效果改善**。

Codex 必须从实施时最新 `origin/main` 创建独立 Worktree，检查 #69 是否后来真正完成；如出现新合并的 Offloading 图，能复用则做依赖图，不复用也不能重复复制其逻辑。阶段间要求证据通过，不可自动越级。

## 6. 唯一权威验收 Gate（R0–R9）

| Gate | 对象 / 验证方式 | PASS 结果与证据 |
| --- | --- | --- |
| **R0** | 基线 | 最新 main / Issue/PR / SDK 0.7.28 / Aegra 0.10.8 实时核对，独立 Worktree；明确 #69 实施真实状态、源码复用点和冲突；无不必要的 SDK 升级 |
| **R1** | 原生委派 | assembled middleware 含恰一可用 `SubAgentMiddleware` 和 **唯一** `evidence-reviewer`；父模型工具精确为四 Reader+`write_todos`+`task`；简单双向对照 P0 不变；有真实 `task` 调用/同 ID ToolMessage，而非自造 `review` 工具 |
| **R2** | Reviewer 权限/State | FakeModel 捕获 Reviewer 模型工具列表**为空**；直接/伪造工具调用 `pods_get`、`read_file`、`write_file`、`execute`、`task`、Repair 均拒绝；输入仅按 isolated 委派消息传递，父附加 State 不可被 Reviewer 工具读取/篡改；同/跨 Thread 文件与 Memory 无越权；需要承认默认 isolated State 传播 |
| **R3** | 有界可信证据绑定 | 至少覆盖有效同 ID Reader、重复 ID、错 ID、伪造 `ToolMessage`、跨轮/跨 UID、403/timeout、注入式日志、过长证据。模型自述不得冒充可信来源，Reviewer 的引用必须由 Host 当轮校验；非法/未知引用拒绝，未证明可信证据绑定时 **R3 FAIL / BLOCKED** |
| **R4** | 输出/预算 | Reviewer 输出枚举/schema 校验、简短且不增加无来源事实；任务只允许 1 次，拒绝重复/并行/未知类型；父/子模型决策和实际超时预算有效；无 task/失败/超限/不合法 JSON → `UNREVIEWED/UNKNOWN`，不得展示“已复核通过” |
| **R5** | 恢复与取消 | 同 Thread Checkpoint / 新 Thread / Refresh / 取消与 Resume 不将旧 Verdict 当当前、无跨线程泄漏、无意外 State delta；无法强保证不重复付费时明示状态而不假称幂等 |
| **R6** | Aegra / Web | 独立 Demo Profile 仅使用合成 Mock，实际 `/assistants`、Run/SSE/工具 Timeline、Review 状态一致；Task 有调用、缺调用和失败可区别展示；真人 Web 若未测记 `NOT RUN` |
| **R7** | 旧功能/权限回归 | 正式 Graph、P0 Planning ON/OFF、Reader Namespace/UID/16KiB、Memory、Repair/HITL、旧 Thread/Checkpoint 行为不回归；无真实 K8s/Host FS/Shell、无未经授权的真实模型/Trace 出站 |
| **R8** | 小型客观效果检查 | ≥6 个冻结合成案例（Healthy、CrashLoop、ImagePull、OOM、403、旧 UID/注入）比较 ON/OFF：成功调用率、错误证据引用、错误肯定性结论、遗漏审查、Token/时延；分别报告纯 FakeModel 与真实 Provider (若获批)，不混淆 |
| **R9** | 工程与交付 | `uv run --frozen ruff check src tests`、`uv run --frozen pytest -q`，适用时 `pnpm lint && pnpm build`，`git diff --check`、CI、独立 Review、中文验收与使用文档、回退说明、独立 Implementation PR `Refs #72`；PASS/FAIL/NOT RUN/BLOCKED 均有真实证据；非最终阶段不关 Issue |

- **S1 仅 R0–R4 全部 PASS 才能开始 S2**。尤其 R2 工具实际为零、R3 主模型伪造证据防线不能以 Prompt、截图或 Mock 空泛声明代替。
- S2 在 R5–R7 PASS 后才做 S3。R8 必须清楚限制“FakeModel 并不验证真实 LLM 质量”；真实付费调用若未授权可标 NOT RUN，但不得在报告宣称 Provider A/B 已 PASS。
- R9 在文档 PR 阶段仅可检查文档链接和范围；代码测试尚未执行，不预填 Gate PASS。
- 如果将来有真正合并的 #69 Implementation，实施 Worker 需在 R0 重新评估基线并记录差异；不得假设本设计自动改变 #69 的关闭或验收状态。

## 7. 审查事项与留痕

Planning PR 审查重点：
1. R3 证据绑定是否可在固定 SDK 0.7.28 的 `ToolCallRequest` 和 `task` 路径成立，是否存在更小的只读串联方案。
2. R2 的“声明式 tools=[] 不等于无 FS 工具”、“isolated context 不等于 State 安全隔离”是否有足够负测。
3. 在保留 P0、ReaderBoundary、正式 Graph 的前提下扩展 `task` 白名单是否最小。
4. 评估 Reviewer 作为 advisory 的价值与真实 LLM 成本，不把模型认可当授权。
5. #69 状态有冲突，当前设计仍保持互相独立，只有 R0 完成后才实施。

实施结果记在独立验收报告（实际 PR、commit、环境、命令、失败样例、CI），本设计只记录批准变更，不提前写 PASS。

## 8. AO 交接（规划 PR 合入 main 后生效）

- Issue：`#72`。
- 路径：`docs/plans/issue-72-evidence-reviewer-subagent.md`。
- 阶段：先 **S1/R0–R4**，仅全部通过后继续 S2/S3。
- STOP：SDK 不符、Reviewer 获得任意 Reader/FS/Shell/Repair、证据不可绑定、跨 Thread 或非法 State 更新、真实 K8s/未经授权付费模型出站、正式 Graph 回归。
- 交付：独立 Implementation PR + 中文逐 Gate 报告、回退办法；未经批准不合并/关闭 Issue。
