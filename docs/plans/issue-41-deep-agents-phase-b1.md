# Issue #41 · Deep Agents Phase B1：Planning / Todo / Replanning 设计与执行计划

> - GitHub Issue：https://github.com/Vc-great/kube-triage-agent/issues/41
> - 状态：Proposed（仅规划；未实施 B1；待 Planning PR 人工审阅/合并）
> - 规划 PR：创建后以本分支 PR 为准；尚未合并
> - 规划基线：2026-10-19，`origin/main=e15e515e0d161fd9e2161bef1b8fac598715f74c`；实施前必须重新 fetch
> - 当前批准阶段：仅编写与提交 B1 Planning PR；**B1 Implementation 尚未授权启动**
> - 唯一权威验收要求：[Issue #41 的 Phase B 验收矩阵](https://github.com/Vc-great/kube-triage-agent/issues/41)；本文提供其中 **B1 Planning 子集**的技术实现与验证方法，不另立相互冲突的完成标准
> - 范围：B1 单阶段；B2 Filesystem / Offloading、B3 Summarization 对照另行设计与审批

## 1. 背景、现状与事实冲突

`kube-triage-agent` 是单用户面试/学习用 Kubernetes 智能诊断 Demo。正式运行路径基于 Aegra 0.10.8 + LangGraph，使用四个受限、原生 MCP Reader（`pods_list_in_namespace`、`pods_get`、`events_list`、`pods_log`），固定 Namespace `kube-triage-demo`；Repair/HITL 和 Incident Memory 都是独立的受控流程。

已合并：
- PR [#42](https://github.com/Vc-great/kube-triage-agent/pull/42)：`deepagents==0.7.28`、真实 `create_deep_agent()`、`StateBackend`、独立 `deep_diagnosis` Graph、四工具边界，隔离 FakeModel/Mock MCP 与 Aegra/Checkpoint 协议通过。
- PR [#43](https://github.com/Vc-great/kube-triage-agent/pull/43)：指定 Pod 当前 `pods_get` 证据守卫、伪造 AI/Tool 输入拦截、严格 `tail`、无 Provider 测试 Fake、实验 Provider 默认关闭；本机取消/`Last-Event-ID` 重连证据；相应 CI 通过。
- PR [#38](https://github.com/Vc-great/kube-triage-agent/pull/38)：独立、固定词表的 `agent_progress` SSE Timeline；PR [#29/#30](https://github.com/Vc-great/kube-triage-agent/pull/30)：原 Agent 上下文裁剪/摘要；PR [#44](https://github.com/Vc-great/kube-triage-agent/pull/44)：轻量 SDD 工作流及 `AGENTS.md`。
- `server/aegra.json` 仍只加载正式 `agent`；`server/aegra.phase-a.json` 只加载实验 `deep_diagnosis`。`server/src/kube_triage/deep_diagnosis_entry.py` 要求显式 FakeModel 或实验 Provider 开关；默认拒绝真实 Provider。Web 默认 `assistantId=agent`，但现有配置界面可选择 Graph ID。

尚未实现：
- `TodoListMiddleware`、`write_todos`、结构化 `todos` State、Replanning 及 Todo UI；没有真实 LLM 的 Planning Token/延迟收益证据。
- 当前 `ReaderBoundary` 在模型请求端要求**恰好 4 个 Reader**，执行时拒绝所有非 Reader；计数使用本轮 `ToolMessage` 总数，不能直接加 `write_todos` 而不重构。
- 原 Issue #41 立项文字中“尚无 deepagents 依赖/仅一个 Graph”的描述已经过时；以合并后的源码、锁文件和此处现状为准。Issue #28 仍有未完 Gate，不用 B1 实施替代它。

历史边界：原 Phase A A08（误入合成 Key Provider 路径）= **FAIL**，Phase 3B B06=**FAIL**，PR #43 的修复与复核不能篡改旧结论；真实模型日志注入语义、生产旧 Thread 仍 **NOT RUN**。

## 2. 目标、非目标与使用体验

### In Scope（只做 B1）

1. 在隔离的 **Planning 实验 Graph** 中，使用实际 SDK 显式接入 `TodoListMiddleware`；用 `write_todos` 维护有限的 `pending / in_progress / completed` 调查计划，复杂任务可调整计划；普通问候、直接回答和简单查询不得强制规划。
2. 将**四个 Kubernetes Reader** 与**一个仅操作本地 Graph 状态的 Harness `write_todos`** 清楚分层：模型端可见集与执行端硬白名单一致；Reader 仍强制验证 Namespace、参数、Tool ID、超时、16 KiB 响应上限。禁止 `task`、Host FS/Shell/`execute`、Filesystem 读写删、Repair，以及其它未知工具。
3. 计划是低信任工作状态，不作为 Pod 当前证据、根因证明、HITL 审批或 Memory 写入授权；保持 PR #43 的证据守卫与客户端预置 AI/Tool 拦截。新模型回合不得用旧 Thread 的 Todo 或历史状态冒充本轮调查。
4. 证明 `todos` 随 Aegra State/Checkpoint 保存，取消/重连及新轮次语义清晰；通过现有 SSE/React Stream 以**只读、最小 UI**展示真实的 Todo 列表及其更新；不能显示模型隐藏思维。
5. 在纯合成条件下进行 Planning OFF/ON 成对对照，观察额外模型调用、Todo/Reader 次数、时间、失败/回退和证据校验；真实 Token 和诊断质量只用实际 Provider Usage 与真实人工/规则评分测量，未经事前授权必须记 NOT RUN。

### Out of Scope

- Phase B2 虚拟文件读写/Context Offloading、Phase B3 Summarization/真实模型大规模 A/B，Subagent、Skills、RAG 或新的 Provider/数据库/事件服务。
- 替换正式 `agent`、修改 `/repair-demo`、Memory/HITL/Repair、迁移历史 Checkpoint、在生产环境启用实验 Graph。
- 在真实 Kubernetes 创建/删除/patch/scale、扩大 RBAC 或直接修改稳定 Compose；任何付费 Provider 测试及发往 Langfuse/外部的合成或真实内容都需独立明确授权。

### 代表场景（预期，不是已实现）

- 简单：`你好`、`检查 Pod payment` 的单项查询，无需建立 Todo 也可以按既有证据守卫答复。
- 复杂：`调查 Pod payment 多次重启，结合状态、Event、日志交叉验证后汇报` → 创建 2–4 个可执行步骤，执行并更新 Todo，Reader 失败时重排或保留未完成并解释不确定。
- 阻断：403、404、连接超时、日志注入、Tool Call 配对错误、预算耗尽、取消 Run → 不能将阻断步骤标 `completed`，不能凭 Todo 宣称正常。

## 3. 方案选型与取舍

| 方案 | 优点 | 代价/风险 | 决定 |
| --- | --- | --- | --- |
| **隔离 B1 Graph + 官方 TodoListMiddleware** | 复用已验收 Phase A、安全边界清晰、A/B 可并行对照和撤销；真实 Harness 练习 | 新 Graph ID、Middleware 顺序及预算需验证 | **采用** |
| 直接在现有 `deep_diagnosis` 开启 Todo | 代码少 | 会改变 Phase A 的基线和旧实验 Checkpoint，难以严格比较 | 不采用 |
| 在原 `graph.py` 手写规划状态节点 | 复用已有 Runner | 重复实现第三方 Todo 能力且改变正式诊断 | 不采用 |
| 每个请求强制 Planning | UI 统一 | 简单查询增 Token/时延，官方评测不支持普遍有益 | 不采用 |

**推荐注册**一个新的实验 `graph_id=deep_diagnosis_planning`，保留 `deep_diagnosis` 为 A 组；实验 Aegra 配置应明确、受控，默认正式 `server/aegra.json` 不变。新 Graph 从 Phase A 的构建工厂复用 Reader、证据守卫和无 Provider Fake，不复制第二份 MCP 校验/答复逻辑。实际注册方式以 Aegra/SDK 兼容验证为准；任何影响 Phase A 默认行为或全局 Profile 合并的实现必须停下评审。

官方依据：Deep Agents 0.7 移除了默认 Todo；显式使用 `from langchain.agents.middleware import TodoListMiddleware`。`write_todos` 每次**替换整个列表**，官方状态值只包含 `pending`、`in_progress`、`completed`，同一模型回合最多调用一次。需要按锁定 `deepagents==0.7.28` 实际 wheel/`langchain` 依赖签名再次核对，不能拿最新 Reference 的签名视为旧 wheel 已测。

## 4. 技术设计与关键契约

### 4.1 Graph 及 Middleware

预期链路：

~~~text
Aegra (独立实验配置 / 独立 Graph ID)
  └─ deep_diagnosis_planning (create_deep_agent)
       ├─ TodoListMiddleware  (write_todos → state.todos，仅本地)
       ├─ B1 ToolBoundary     (模型工具=4 Reader+1 Todo，执行时再次检查)
       ├─ Phase A 现有 Reader/证据守卫（复用，不弱化）
       ├─ Reader MCP: call_tool → validate_call → tools/list
       └─ StateBackend（Phase A 已引入；本阶段仍不开放 Filesystem）
        → Aegra State/Checkpoint/SSE → 最小 Plan 展示
~~~

- 先在锁定 SDK 确认 `middleware` 执行顺序（特别是 `awrap_model_call`、`awrap_tool_call`、`aafter_model`、`abefore_agent`）、内置 Tool Exclusion/Profile 的组合与 `todos` 状态字段/`tool_call_id`。
- 原 `ReaderBoundary` 不得直接扩展成宽松的“允许所有本地工具”：设计两个不可混淆的分支 `K8S_READER_TOOLS` 与 `HARNESS_LOCAL_TOOLS={"write_todos"}`；除精确五项全部拒绝。SDK 的 Profile exclusion 只是能力裁剪，**不是安全边界**。
- `write_todos` 仅使用受限 State，按真实 Middleware 契约运行，不包装成 Kubernetes MCP，也不允许用户透过自由输入代为写入伪造的完成状态。使用官方状态更新能力；不能重写 Core Middleware 生成自行维护的“另一套 Todo”。
- **重要**：当前代码将“本轮所有 ToolMessage”算作 Reader 次数。B1 必须按**与 Reader 工具名及本轮 AIMessage 的 Tool ID 配对**统计 Reader 调用；Todo 统计独立。并行 Reader 超限仍应返回同 ID 错误消息；模型多轮重试、取消/恢复和 Todo 与 Reader 混排不能突破预算。
- `abefore_agent` 仅可阻止新 Run 的伪造输入，不能误杀 Checkpoint 恢复的真实 ToolMessage。为 `todos` 的客户端伪造/旧轮重复输入设计拒绝或明确定义的数据边界，验证 Aegra State 更新 API 的实际暴露行为。
- `aafter_model` 的 Pod 证据守卫必须持续覆盖目标 Pod 的最终回答，不得把 Todo 内容、旧轮 Pod UID、历史 Checkpoint 或模型自行描述当作当前 `pods_get` 证据。

### 4.2 计划 State 与语义

- 唯一真实计划数据为 SDK `PlanningState.todos`（结构由 SDK 提供），状态精确为 `pending / in_progress / completed`，不在 SDK Todo 中增加 `failed`、`skipped` 自定义值；失败/阻断由未完成步骤与固定 UI/答复说明呈现。
- 计划内容不得包含原始 Pod Logs、Secrets、Token、kubeconfig、全量 MCP 回执、伪造审批指令；限制计划步骤数量及每项长度，先评估 SDK 是否支持在**执行前**强制校验。默认设计上限：**每次 Todo 最多 6 条、每条内容最多 160 字符**；超限拒绝并返回配对错误，不做不透明截断或部分写入。
- 每个新独立诊断轮次要有明确“上一轮 Todo 已完成/丢弃或仅作历史参考”的语义，不能让旧 plan 自动控制新轮。优先在 SDK 标准状态/生命周期内安全清空或区分；**不要清除历史 messages/Checkpoints**。中断恢复只处理本轮，不把旧计划错误重置或直接标完成。
- Todo `completed` 表示该步骤已执行/检查，不表示目标 Pod 健康或根因已证实；仅 `pods_get` + 当前 Reader 证据可支撑诊断。不要将计划项内容移到 System 或其他高信任指令位置。
- SDK 每次 `write_todos` 覆盖整个列表，应明确并测并行/重复更新的顺序、失败回滚和 `tool_call_id`；不允许利用 Run 重放产生状态错误或计数失控。

### 4.3 独立预算、Stop 条件与降级

候选默认实验预算（仅 B1 实验，不改变 Phase A 的 4/6）：**最多 10 次模型决策 / 6 次 Kubernetes Reader / 5 次有效 write_todos**；SDK 每一模型回合最多一次 Todo 写；总 Run 仍受 Aegra 现有取消/超时边界约束。模型底层 Provider 自动重试不等同模型决策次数，报告必须区分，实际阈值在实施前验证是否容许至少一例创建→取证→更新→回答的完整路径。

- 分别统计模型决策数、Provider 请求尝试数（能观测才统计）、Reader 尝试数、Todo 写尝试及成功数、总回合/延迟。全部预算作用于当前 Human 轮次；历史 ToolMessage 不计入本轮。
- Todo 超限或非法内容：返回同 `tool_call_id` 的失败 ToolMessage，状态不发生未校验更新；不能绕过 Reader。模型总预算耗尽：安全回答“诊断未完成/仍有待核验”，无隐式额外模型请求。
- Reader 403、404、超时与没有目标证据：允许在预算内 Replanning，但不得生成虚假成功步骤；后续没有可行只读手段就停止，不能自动“修复”K8s。
- 取消/重连：展示上以 State/Checkpoint 为准；客户端临时事件可能丢失，不能假称可以从历史完整重建所有 SSE 过程。
- 不引入第三方限流服务或 Redis 新业务键；若 SDK 的中间件难以限制其本地副作用，记录 BLOCKED 而不是只靠提示词保证预算。

### 4.4 UI、SSE 与可观察性

- 现有 `apps/web/src/providers/Stream.tsx` 已有 `useStream`、`StateType.messages` 和 Custom Event 分流；现有 `agent_progress.py` 使用固定词表和字段白名单。
- **主推荐**：将 Graph 返回的 `todos` 作为**结构化状态**通过 Aegra SSE values/updates 读取，前端仅在 Planning Graph 且状态合法时显示可折叠 Plan 列表；不要把 Todo 变成聊天 AIMessage，也不需要重新建自定义事件总线。若实际 SDK 事件不足以实现实时变化，才评估最小脱敏 `agent_progress` 扩展，并给出实际可达性测试。
- 前端显示只依据校验后的 `content/status`，对未知状态、超长文本、用户切换 Thread 和 Run 取消采取拒绝/隐藏/清除策略；刷新后如 Aegra State 可读，则按持久状态重新展示，不能将 ephemeral 事件当持久证据。
- 历史 `agent`、`deep_diagnosis` 及现有 Timeline、Tool 卡、Memory/HITL 卡不应出现空白或错误的 Plan UI。
- 不显示 CoT、模型内部 JSON 或敏感日志；不默认开 Langfuse 外传。按 #39 既有链路做可观测性需求记录，不新建 SDK exporter。

## 5. 验收方式（映射 Issue #41，非第二套权威 Gate）

由 Issue #41 的 Phase B 矩阵最终裁决；本次 Implementation PR 只申请 B1 Planning 涉及的子集，其他 B2/B3 Gate 继续 NOT RUN/待后续阶段。

| Issue Gate | B1 的测试与交付证据 |
| --- | --- |
| **B1** 简单/复杂计划 | FakeModel 场景：普通问候/简单单 Pod 可直接答复；复杂调查建立→状态更新→完成；失败后 Replanning/停止，不标伪成功；Aegra State 中 `todos` 实际字段 |
| **B2** Replanning/预算 | 无目标 Pod、403/404/超时、预算耗尽、并行/重复 Todo、取消、重连；单次 Tool ID 一一对应、独立 Reader/Todo/模型计数与失败退化 |
| **B5** 安全与记忆 | MCP 跨 Namespace/参数拒绝；未知 Harness/Repair/Shell/文件工具拒绝；伪造 AI/Tool/Todo、UID 冲突、日志注入哨兵不作为指令或当前证据；不破坏既有 Checkpoint/HITL/Memory |
| **B6** UI/Trace | 隔离 Aegra SSE + React（如适用）验证 `todos` 来自真实状态，更新/刷新/线程切换/取消结果一致；日志/Secret/CoT 不泄漏；Langfuse 云端实际验收 **NOT RUN（默认）** |
| **B7** 离线 A/B | 固定 Synthetic Golden（CrashLoop / ImagePull / OOM / Healthy）+ 至少 2 个复杂合成案；Planning OFF/ON 使用相同 Mock/同源 FakeModel，单列调用/状态/失败/延迟；不能将 FakeModel 视为真实质量或 Token 收益 |
| **B8** Real LLM | 本 PR **NOT RUN**；只有用户对模型名/调用次数/费用上限/合成数据网络出口另外明确批准后才独立 Gate |
| **B9** 工程交付 | 最新 main、单独 Worktree、校验依赖 SDK、Ruff / pytest、涉及 UI 则 web lint/build、必要的 localhost Aegra/Mock MCP 协议 Smoke、CI、中文验收及独立 Review；非最终阶段 Draft Implementation PR（`Refs #41`），不关闭 Issue |

建议新增独立可复现的小型 B1 合成用例和 Validator 规则，不修改、重新打分或覆盖历史 Golden 与 #12/#13 成绩。至少保留以下原有回归：Phase A Reader 预算、证据守卫、Fake Provider 网络阻断、Thread/Run/Checkpoint 恢复、cancel、`Last-Event-ID`；原正式 Graph/HITL/Memory 不因新 Graph 发生行为变化。

**状态和证据**：所有 Gate 用 `PASS / FAIL / NOT RUN / BLOCKED / UNKNOWN`，注明源码、FakeModel、Mock MCP、隔离 Aegra、浏览器手动、真实 Provider 或真实 Kubernetes 的证据等级。不存在的 Trace 不得标 PASS。PR #43 的历史 A08=FAIL 及 B06=FAIL 不覆盖。

## 6. 执行计划、停止条件、回退

### Planning PR（本次交付）

- [x] 核对 Issue #41、PR #42/#43、最新 `main`、`AGENTS.md`、`docs/agent-workflow.md`、现有 Deep Diagnosis、SDK 及 SSE/Web 路径。
- [x] 编写本设计，基于官方 SDK 明确 Todo 工具/状态、边界、取舍、阶段和 Gate 的实施方法。
- [ ] 纯 Markdown 提交独立 Planning PR，`Refs #41`，**不合并、不修改 Issue 验收权威、不实施业务代码**。
- [ ] 用户人工审阅并合并到 `main`；随后才可启动 AO/Codex Worker。

### B1 Implementation（仅在上述 Planning PR 合并且获授权后）

1. AO 指派 Codex 从最新 `origin/main` 的独立 Worktree 读取 Issue、`AGENTS.md`、本文件与 PR #43 的真实代码/测试；确认锁定 SDK 实际 Middleware API。
2. 先落地隔离 `deep_diagnosis_planning` + Todo State 与五工具权限分流，完成模型可见工具集合与执行前拒绝测试；**原 `deep_diagnosis` / `agent` 不变**。
3. 补全 Reader/Todo/模型独立预算、重复/并行 ID、拒绝伪造 Todo 和目标 Pod 证据守卫回归；验证 SDK 原生 Todo 写入无部分状态。
4. 再做最小 UI/state 接入与隔离 Aegra SSE/Checkpoint 端到端测试；优先使用已有 Stream/Timeline 组件；浏览器实测未做就标 NOT RUN。
5. 最后跑 OFF/ON 固定合成用例、Ruff/pytest/Web/CI，记录额外调用/时延与语义未测；独立 Reviewer 复审修复，提交 B1 专用 Draft PR。不得继续 B2/B3、合并或关闭 #41。

### 风险、停止条件与回退

- **P0 / STOP**：`write_todos` 或任何新增工具可调用 K8s 写操作、Host FS/Shell/`task`、绕过四 Reader/RBAC/Namespace，或破坏 HITL/Repair/Memory；需要提升权限时必须停止另行授权。
- **P1 / STOP**：Todo 工具过滤/执行边界不一致、模型工具集合意外超出五项、Reader 预算被 Todo 计数污染、Tool ID 断链、客户端伪造 Plan 冒充可信证据、Checkpoint 状态不兼容、Prompt Injection 被提升为当前诊断证据。
- **BLOCKED**：在锁定 SDK 下无法无侵入接入 `TodoListMiddleware` 或无法控制状态写入时先提出兼容性证据/替代方案；不得重写大半框架或跳过验收。
- **费用/隐私 STOP**：未经单独授权不得连真实 Provider、真实 Kubernetes 或上传数据到 Langfuse Cloud；不得读取/回显私有 `.env`、Token、kubeconfig 或真实 Pod Logs。
- **稳定环境 STOP**：禁止操作用户正常运行的 Compose、Pod、数据库卷。隔离环境需事前确认资源归属，用新端口/专有 Compose/独立数据库，只能精准清理本任务创建的资源。
- **回退**：保持原正式配置与原 Phase A 实验 Graph，移除/不启用 B1 Graph 即回退；不删除/更改历史 Thread、Checkpoint、Golden。不能保证版本兼容时保持实验默认关闭。

## 7. AO 交接（**只有本 Planning PR 合并后才有效**）

- 仓库：`Vc-great/kube-triage-agent`
- Issue：[`#41`](https://github.com/Vc-great/kube-triage-agent/issues/41)
- 已批准设计路径（合并后）：`docs/plans/issue-41-deep-agents-phase-b1.md`
- 本轮实施阶段：**Phase B1 Planning only**；不进入 B2/B3。
- 先读：`AGENTS.md`、本计划、`server/src/kube_triage/deep_diagnosis.py`、`docs/issue41-deepagents-phase-a-validation.md`。
- 严禁：真实 Kubernetes 写入、扩大 Reader、真实模型付费调用、外传真实数据、修改稳定资源、自动合并或关闭 #41。
- 交付：B1 独立 Implementation PR、逐项 Gate 证据、真实 Head SHA/CI、功能/风险对照、必要 Reviewer 修复与 STOP/GO 建议。
- AO 的实际任务提示词应尽量保持 **1–3 KiB**；不要复制本文到 AO Task。未合并时严禁令 Worker 假装本文件已存在于 `main`。

## 8. 参考与变更记录

- Deep Agents 0.7 Changelog：https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/CHANGELOG.md
- Deep Agents Overview：https://docs.langchain.com/oss/python/deepagents/overview
- Deep Agents Profiles：https://docs.langchain.com/oss/python/deepagents/profiles
- TodoListMiddleware Reference：https://reference.langchain.com/python/langchain/agents/middleware/todo/TodoListMiddleware
- 项目工作流：`AGENTS.md`、`docs/agent-workflow.md`、`docs/plans/README.md`
- 2026-10-19：依据 `main=e15e515` 与用户确认的 B1 方向起草规划；尚无 B1 实现或实际验证，Planning PR 状态以 GitHub 为准。
