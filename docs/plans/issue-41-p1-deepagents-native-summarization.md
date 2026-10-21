# Issue #41 · P1 Deep Agents 原生 Summarization：轻量 Demo 集成与证据保护

> - 关联：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)；唯一权威 Phase B Gate 仍是该 Issue 的 B1–B9，**此文只定义本阶段可执行方案和测试映射，不重写/降低 B4/B5/B8**。
> - 状态：**Proposed / Planning PR（纯文档，代码尚未实施）**。
> - 核对基线：2026-10-21 `origin/main=d031cc9aad35e0b6b57ab9da4c61ffd3cedd9214`；[PR #66](https://github.com/Vc-great/kube-triage-agent/pull/66) P0 Core Demo 已合并，[main CI](https://github.com/Vc-great/kube-triage-agent/actions/runs/39546037355) Python/Web/Compose PASS；Issue #41 仍 Open。
> - 关联已批准路线：[Deep Agents 最短 Demo 交付](issue-41-deepagents-demo-closeout.md)；[P0 使用与残留限制](../issue41-p0-demo.md)、[旧 B2 写入阻断](issue-41-b2-scope-and-b1r-pilot-readiness.md)。
> - **当前仅批准 P1 原生 Summarization**：复用 `deepagents==0.7.28`，通过独立实验 Graph 接入，使用冻结/人工合成 Mock Reader 历史和已批准 CPA `gpt-6-luna` 少量 Smoke；**不批准**真实 Kubernetes 出站、Repair、Filesystem 面向网页开放、Subagent/Skills、Langfuse 外传、P2 文件阶段、20 Run Formal。
> - 用户偏好：尽快完善单用户 Demo，不为非关键 Rubric 误报/大规模对照反复追加实验；已发现的实际安全/State 缺陷不以 Demo 为由豁免。

## 1. 已有实现与问题定位

### 现成基础

- `server/src/kube_triage/deep_diagnosis_planning.py` 是真实 `create_deep_agent` + `TodoListMiddleware` + 4 Reader + 本地 `write_todos`，目前注册 `HarnessProfile(excluded_middleware=frozenset({"SummarizationMiddleware"}))`，显式禁摘要。
- `server/src/kube_triage/deep_diagnosis.py` 也禁摘要；必须继续保留作为 Planning OFF 基线。`server/aegra.phase-b1.json` 注册两张图；`server/aegra.json` 仅有正式 `agent`。
- `make dev-deep-demo` 已提供真实 `gpt-6-luna` + Chat Completions + **合成 Mock MCP** 的浏览器入口，结构化 Todo/SSE/Checkpoint/取消经过 AO Browser 和实际模型有限 Smoke。P0 独立 Worker 队列前缀，默认禁 Langfuse/OTel/代理继承。
- `server/src/kube_triage/context.py` / `context_summary.py` 是**正式 Graph 的独立摘要实现**，本 P1 不复用到 Deep Agents（避免双层摘要）也不修改。
- P0 留存限制：取消/Responses 意外路由的历史失败不得覆盖；使用共享开发 DB，Aegra SDK DB fallback/reaper 没有按 Redis Worker 队列完全隔离；不能并行做崩溃恢复实验。

### 锁定 SDK 源码已核对（不是猜测的最新版 API）

明确以 GitHub tag [`deepagents==0.7.28`](https://github.com/langchain-ai/deepagents/releases/tag/deepagents%3D%3D0.7.28) 和仓库锁文件为准：

1. `deepagents/graph.py` 的 `create_deep_agent` 自带原生 `create_summarization_middleware(model,backend)`，`_apply_custom_middleware` 根据 `middleware.name` **按原位置替换**已有同名 Middleware；**不需要重写摘要器，也不能仅叠加两个同名实例**。[源码](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/graph.py)
2. `compute_summarization_defaults` 根据 `model.profile.max_input_tokens` 使用 `trigger=("fraction",0.85)`、`keep=("fraction",0.10)`；当模型 Profile 没有合法 `max_input_tokens`，回退到 **`trigger=("tokens",170000)`、`keep=("messages",6)`**，无法用短合成 Demo 稳定触发。[源码](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/middleware/summarization.py)
3. 原生 `SummarizationMiddleware` 构造器支持 `trigger`/`keep`/`trim_tokens_to_summarize`，默认构造器截断预算 4000，但 `create_summarization_middleware` 工厂的 `trim_tokens_to_summarize=None`；**不应在演示时把整个巨大历史无上限送给摘要模型**。优先显式构造 **SDK 原生**对象：`trigger=("messages",18)`、`keep=("messages",8)`、`trim_tokens_to_summarize=4000`，先以锁定 SDK FakeModel 验证。这些数值只适用于独立合成 Demo Profile，不作为正式模型 Context Window 精确阈值声明。
4. 原生摘要在准备压缩时并行执行历史 `backend` Offloading 和 Summary；**Offloading 失败时 SDK 可能继续完成摘要并发出 warning**，不等于旧证据已可恢复，也不能将 warning 路径自动标 PASS。SDK 还可能通过内部 `_summarization_event`/后续 State 更新改变历史消息视图；**务必实测真实 Checkpoint、ToolCall/ToolMessage 成对性与来源可追查性**。
5. `HarnessProfile.excluded_middleware` 的注册/合并使用排除项的并集；同一进程内同时注册默认 OFF/ON Profile 可能把新 P1 摘要也排除。单独注册新名字但复用同一 `openai` Provider **不能假设**能抵消旧排除项。应**独立 Aegra 进程、单独配置**，再验证实际 assembled middleware 中只有**一个** Summary 实例。
6. `StateBackend` 的隐藏 `/conversation_history/` Offloading 仍涉及内部 State 写入，**不等同安全启用模型 `write_file/read_file`**；PR #50/#52 已记录写后拒绝不回滚、并发配额竞态与客户端 `files`/`aupdate_state` 绕过。本 P1 必须隔离和标注，仅合成单用户数据；不得因 Summary 成功把原 Issue B3 文件安全 Gate 判 PASS。

## 2. 本轮目标、非目标和可见体验

**P1 必须达成的最小用户体验**：不改变 P0，新增一个可在本机单独启动的 `Deep Agents Planning + Summary` 演示入口：持续输入合成多轮复杂诊断请求，在真实 `create_deep_agent` 的原生 `SummarizationMiddleware` 满足阈值时发生一次可审计的 Summary；后续模型仍可读取新的合成 Reader、维护 Todo、正确报告最新可验证状态；用户可在 Aegra State/SSE/简单状态提示中知道“摘要已触发/是否成功”，但不需要显示隐藏思维、Summary 全文或添加新前端管理台。

**非目标**：P1 不追求 A/B 质量显著优于 P0、不实现正式长历史 Context 迁移、不开放 `write_file/read_file`、不自造压缩算法、不默认生成任意文件到宿主 FS、不实现分布式 State 事务；不复测 P1-B 冻结四槽或额外 20 Run，也不更新 Rubric v1。Subagent、Skills、Memory、Repair/HITL 均维持原实现/关闭。

### 关键选型

| 方案 | 代码/风险/演示效果 | 决策 |
| --- | --- | --- |
| **独立 P1 Graph + 原生 `SummarizationMiddleware`（显式有限参数） + 现有 Mock/Web/Aegra** | 只增加最小工厂参数、入口、测试和启动 Profile；能稳定触发原生 SDK 行为；避免同进程 Profile 排除项污染 | **主方案** |
| 修改已有 `deep_diagnosis_planning` 直接删除排除项 | 更少文件，但改变 P0/旧 Thread 的语义，可能被并集再次禁用 | 拒绝 |
| 复制 `context_summary.py` 或自定义 Summarization Node | 看似熟悉，实际不再证明 Deep Agents 原生能力且重复代码 | 拒绝 |
| 为 Summary 顺带启用完整 Filesystem/Offloading 工具 | 触及 B2 已知安全阻断、显著增加工作量 | 拒绝 |

## 3. 实现结构、数据与 Middleware 契约

### 3.1 隔离 Graph / 启动 Profile

建议新增：
- `server/src/kube_triage/deep_diagnosis_summary.py`：最小工厂，**复用**现有 PlanningBoundary、Reader 定义、系统 Prompt、预算及 Todo；允许仅此实验 Graph 构建**一个** native Summary Middleware。优先给原 `build_graph` 增加仅内部可用的显式 Summary 配置参数，不复制整份 9 KB Graph；**默认原 P0 输出/接口不变**。
- `server/src/kube_triage/deep_diagnosis_summary_entry.py`：继承既有 Provider/FakeModel 严格门控；只在已授权 Demo Profile 下启用；默认 Fail Closed。
- `server/aegra.phase-p1-summary.json`：**只注册** `deep_diagnosis_summary`，不在同一个 Aegra Worker 中注册 P0 OFF/ON Graph；旧 `server/aegra.phase-b1.json` 和正式 `aegra.json` 不变。
- `scripts/dev.py` / `Makefile`：建议新独立 `make dev-deep-summary-demo` Profile，复用现有 supervisor、Mock MCP、DB/Redis 隧道、API/Web 启停、凭据读取、权限/遥测/代理隔离；启动时对本 Graph 配置做专属 `/assistants` readiness，输出不含 Key 的 `assistantId=deep_diagnosis_summary` 链接。
- Web 只做非常小的 Graph 名称/状态文案适配（若实际必要），展示 `Mock Reader + Real LLM + Summary`；不要复制第二套 Chat/Timeline/Todo。Todo UI 只在明确 Graph ID 白名单内显示合法 `todos`，保持旧 Graph 行为；Graph 切换必须新 Thread。

~~~text
make dev-deep-summary-demo
    └─ 原有进程监督 + 仅合成 Mock Reader + 已批准 CPA gpt-6-luna
         └─ 独立 Aegra phase-p1-summary
              └─ create_deep_agent
                   ├─ 原生 TodoListMiddleware + 原有 PlanningBoundary
                   ├─ 原生 SummarizationMiddleware (trigger=18 messages;
                   │     keep=8 messages; trim old input ≤4000 estimated tokens)
                   │    ├─ SDK native summary LLM
                   │    └─ StateBackend: synthetic history offload (受限内部路径)
                   └─ 四个严格 Reader（无 FS 模型工具、无 task/Repair）
              → Aegra State / SSE → Todo、Reader、摘要触发元数据 → Web
~~~

### 3.2 可测试的安全数据约束

1. 只允许由 **Aegra 正常 Run** 创建的合成 Thread 消息和 Mock Reader 结果流入摘要；客户端伪造 Tool/AI、传入 `files`/Summary 私有状态、调用 `update_state` 绕开检查必须被拒或隔离。若 Aegra 默认有可写 State 路径无法用轻量范围封闭，则先让 P1 **仅在独立本地 SDK CLI 无外部状态接口演示**并报告 Web Gate BLOCKED，**不得假设 B2 已修复**。
2. 读写的 Summarization 历史文件只属于 SDK `StateBackend` 的内部演示路径（例如 `/conversation_history/...`），仅存合成对话；不作为新的可执行工具，也不让模型使用 `read_file/write_file`、`ls`、`execute`、`task`；执行侧原四 Reader + `write_todos` 精确白名单不变。
3. **Checkpoint 与当前证据**：区分模型视图压缩、Graph State/Checkpoint 更新、内部历史 Offload 三种实体。必须检查多 Tool Call 与对应 ToolMessage 不被孤立，`pods_get` 当前 metadata UID 不从摘要/日志/旧历史提级，压缩后新一轮仍能重新获取当前 UID。SDK 若不可逆裁剪原始历史、离线 Offload 不可查或混用原旧 Thread，则 B4 不得判 PASS；不要手动伪造配对 ToolMessage 或补写不可追查的摘要。
4. **失败策略**：Summary 模型超时/400/429/异常、取消、Token budget/阈值失配、Offload warning、State 部分写入、文件路径/线程交叉污染必须有安全可观察结果；如果 SDK 默认“Offload 失败继续总结”，本阶段至少输出 `DEGRADED/BLOCKED` 并拒绝将缺失来源的摘要视为可信证据。不能为了让截图显示 Summary 而吞错、强行覆盖老 Message History 或跳过 ReaderBoundary。
5. **配置**：锁定 `deepagents==0.7.28` 与已验 `gpt-6-luna` Chat Completions `use_responses_api=False`。同 `deep-demo` 一样禁止额外 `/v1/responses`、自动 Langfuse/OTel/LangSmith、任意 HTTP 代理、真实 Kubernetes、真实日志、Repair、Host FS；输出前核对唯一已批准 CPA IP/端口。
6. 真实模型请求与 SDK 内置摘要重试次数都要计数，不要把摘要单次请求视作必然无重试。**本阶段少量 Smoke 上限建议 3 个新合成 Thread、最多 24 次可观测 CPA HTTP 请求尝试、串行、单 Run 120 秒、全测试 20 分钟**。上限是安全熔断、不是精确计费；超额 STOP，隐藏网关重试/费用 UNKNOWN。无法以实际实现可靠限制时真实 Smoke STOP，仅交付离线证据。

### 3.3 原生 SDK Preflight：先做最小 Spike

在 Codex Worker 实施前先验证：`deepagents==0.7.28` 的 Middleware 排序、同名替换、Profile 并集、`SummarizationMiddleware.name`、`StateBackend` 的 Offload 状态写入、`model.profile` 阈值默认、`keep/trim`、summary 失败/取消传播；务必使用**锁定 wheel 与 FakeModel/Mock**，不要引入最新 SDK API 或升级依赖。

**成功触发判定必须基于实际事件/模型输入差异/SDK 内部状态，不得只凭日志出现字符串“summarize”**。在 Demo Profile 下确定性准备≥18 条成对、纯合成的历史消息（每条 Reader 输出仍受 16KiB 边界），分别测不触发、触发一次、触发后再次 Reader、取消与错误；验证 `state.messages`/`_summarization_event`/历史 Offload 真实形状之后才决定哪些有限元数据可给 UI。若固定的 `keep=8` 会截断 Tool Call/回执配对，调整只限独立实验参数并说明取舍；不能修改冻结 Golden。

## 4. 分阶段执行与验收证据（映射 Issue #41 B4/B5/B6/B9）

| 步骤 | 交付/验收 | GO 条件 |
| --- | --- | --- |
| **本 Planning PR** | 纯 Markdown，阶段决策及 AO 提示；未执行 SDK/CPA | 审阅并合并至 main |
| **P1-S1：锁定 SDK Spike + 离线负测** | 证明单一 native Summary 的触发与 State/ToolCall 配对；Profile 隔离；Offload 失败显式降级 | S1 PASS 可继续 S2；失败时停在离线工具/报告并 BLOCKED |
| **P1-S2：最小 Graph + Aegra/Web** | 独立 Graph/启动 Profile，合成 Mock Reader、Todo、SSE、Checkpoint、刷新/取消/Thread 隔离，无其它工具/出口 | 离线 Aegra + UI/State 门禁 PASS |
| **P1-S3：有限真实 CPA 合成 Smoke** | ≤3 个新合成 Thread、≤24 HTTP 尝试，记录 Usage/模型回显、摘要触发/续答/失败，合成数据出站 | 只在 S1/S2 安全门禁通过后；不可验证则 NOT RUN |
| **P1-S4：独立 Review/PR** | Ruff/pytest/Web lint/build/CI、同 Head AO Review、中文报告、手册、回滚；用户审阅合并 | 仅 P1 Implementation PR，`Refs #41`，Issue 保持 Open |

本 P1 新增核验项映射原 Issue，不额外建立一份权威 B4：
- **B4 Context 协议**：多次 `AIMessage.tool_calls` + `ToolMessage` 配对、历史 UID/current 证据来源、摘要触发/不触发/超时/错误/Checkpoint/Resume、Offload 可回查和线程隔离。**仅触发摘要 ≠ 整个 B4 PASS**，根据真实覆盖标 `PASS（明确子集）/PARTIAL/BLOCKED`。
- **B5 安全**：日志 Prompt Injection 低信任、Namespace/目标 UID、伪造 State 拒绝、无 FS/Shell/task/Repair/Memory 越权；数据无法溯源时报告未核验而不是确认根因。
- **B6 Web/Trace**：网页/自动浏览器可见 Todo 与摘要状态一致，运行刷新/取消后状态不捏造；Langfuse Cloud 实际 Trace NOT RUN（本次禁外传）。
- **B9 工程**：适用 Ruff/pytest/构建/独立 Aegra FakeModel Smoke、真实 CPA 合成 Smoke 证据、最终 CI、同 Head Review；真人网页验收没进行必须记 NOT RUN。
- **B3/B8 原状态保持**：B3 文件安全依旧 BLOCKED，B8 旧 R05 原 `raw_forbidden_claim STOP` 与 0/2 Pair 保留。Summary 新 Smoke 不能充当 Formal A/B。
- 记录旧 Phase A A08、Phase3B B06 与 P0 的首次误发 `/responses` 和 Cancel FAIL 历史，不追溯重写。

### STOP 与回退

**STOP**：未授权真实 K8s/其它 CPA 出口、任何 Repair/Host FS/文件写工具/`task` 暴露、客户端写 `files`/Summary State 旁路、Summary 断开 ToolCall ID 配对、错误现行 Pod UID、Offload 无法回查却当作可信历史、模型压缩形成伪造 Repair 授权、P0 OFF/ON 被全局 Profile/Thread 污染、未受控重复总结/重试、SDK API 不兼容或要升级 SDK 才能继续。此时提交 BLOCKED 证据，不能扩大范围。

**回退**：禁用独立 `deep-summary-demo`/新 Aegra 配置，不变更 `make dev-deep-demo` 的 Core、正式 `agent`、原 Reader/Repair/HITL/Memory、旧 Checkpoint/Golden；`make dev-stop` 仅停本任务负责的进程。清理测试资源仅限本次专属资源，绝不删除共享开发 DB、稳定卷或历史 Thread。

## 5. AO 交接（Planning 合并后才执行）

仓库 `Vc-great/kube-triage-agent` / Issue `#41`；权威方案 `docs/plans/issue-41-p1-deepagents-native-summarization.md`；**唯一获准 P1 原生 Summarization**，按 `P1-S1→S4` 顺序，不进入 P2 FS、P3 扩展、Formal 20 Run。新 Worktree 从最新 `main`、阅读 `AGENTS.md` 和锁定 `deepagents==0.7.28` 源码、核对 PR #66 实际代码/实验服务安全边界。

优先复用已完成 Demo，不重写 Graph/摘要框架；离线 SDK Spike 与真实 Aegra/FakeModel 先通过，才允许经授权 CPA `gpt-6-luna` 的少量合成 Smoke。无真实 Kubernetes、Secret、Langfuse、Repair、外部 FS；历史 STOP 原样保留。提交独立 Draft Implementation PR、中文验收、真实 CI、Reviewer；**不自动合并、不关闭 Issue #41**。

## 6. 决策记录

- 2026-10-21：用户明确同意 P0 完成后推进 P1 原生 Summarization，目标是 Demo 整体性与最小可用，而非继续扩展 Rubric/Formal。Planning 仅文档。
- 2026-10-21：校验锁定 `deepagents==0.7.28` 上游源码；记录无 Profile 回退 170k 阈值、工厂 trim=None、同名替换、并发 Offload/摘要及失败 warning 的真实行为。实施阶段仍必须以项目锁定 wheel 的离线测试复核。
