# Issue #41 · Deep Agents Phase B2：受控 StateBackend 虚拟笔记与 Context Offloading

> - GitHub Issue：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)
> - 状态：**基础设计 Approved（PR #49 已合并）；B2-A 写入契约修订 Proposed（本 Planning PR 待审）**。本次修订未完成 B2-A 功能或解除 BLOCKED
> - 基础规划 PR：[PR #49](https://github.com/Vc-great/kube-triage-agent/pull/49)（已合并）；本次修订 PR：创建后以 GitHub URL 为准
> - 规划时基线：2026-10-19，`origin/main=951c234c9f27538ac4bbbcd564fcd58674a47834`；执行前必须再次 fetch 和核对锁文件
> - 当前授权范围：**修订 B2-A 安全写入提交契约 + 纯 Markdown Planning PR**。修订合并后先执行 **Compatibility Spike**；只有 Spike 通过及另行批准才恢复 B2-A 实施；B2-B 继续禁止
> - 唯一权威验收：[Issue #41 Phase B 验收矩阵](https://github.com/Vc-great/kube-triage-agent/issues/41)，重点 B3（Filesystem 隔离）、B4（Context 协议）、B5（安全）、B6（UI/Trace）、B7（离线对照）、B9（交付）。本文仅定义 B2 技术与验收方法，**不增加互相冲突的第二套 Gate**。
> - B1-R Real LLM Pilot/Formal：**NOT RUN；必须单独批准费用/请求/合成数据外传**，B2 规划或离线实施不构成该批准

## 1. 背景与现状核验

项目正式诊断 Graph 仍为 `server/src/kube_triage/graph.py`，有四个限定的原生 Kubernetes Reader、Repair/HITL、Memory、Checkpoint，以及 `context.py` / `context_summary.py` 中独立的历史裁剪和摘要策略。B2 不替换原正式 Graph，不迁移历史 Thread 或 Checkpoint。

现有隔离 Deep Agents 演进：
- [PR #42](https://github.com/Vc-great/kube-triage-agent/pull/42) Phase A：`deepagents==0.7.28`、`create_deep_agent`、`StateBackend`，只暴露四个 Reader。
- [PR #43](https://github.com/Vc-great/kube-triage-agent/pull/43) Phase A Closure：目标 Pod 当前回合 `pods_get` + UID/ToolMessage 可信守卫、无 Provider Fake、取消/重连。
- [PR #45](https://github.com/Vc-great/kube-triage-agent/pull/45)、[PR #46](https://github.com/Vc-great/kube-triage-agent/pull/46) B1：隔离 `deep_diagnosis_planning`、显式 `TodoListMiddleware / write_todos`、四 Reader + 一个 Harness Local Tool、独立模型/Reader/Todo 预算、Aegra SSE/Checkpoint/React Plan 展示。`server/aegra.phase-b1.json` 只注册两个隔离 Graph；`server/aegra.json` 仍是正式 Graph。
- [PR #47](https://github.com/Vc-great/kube-triage-agent/pull/47) 和 [PR #48](https://github.com/Vc-great/kube-triage-agent/pull/48)：B1-R 合成 A/B 设计及 **Prep**。PR #48 已合并，`eval/issue41-b1r/` 冻结 6 类合成案例/24 Run（12 对），`scripts/issue41_b1r_prep.py --dry-run` 为进程内 Mock Reader + FakeModel；Runner 自身**不支持真实 Provider**。最终合并后源码恢复 Mock Reader/Socket monkeypatch；PR CI compose/python/web 全绿，报告 451 passed、24/24 Fake Run。原 PR 过程中 UID 冲突与进程污染问题经后续提交修复，但这些证据仍只代表离线协议，不代表真实语义表现。

**新发现的阻断证据（2026-10-19）**：[Draft PR #50](https://github.com/Vc-great/kube-triage-agent/pull/50)（Head `6bba62305f0fae400c6c1c92a9c3a3b02884e14b`；**尚未合入 main**）基于锁定 `deepagents==0.7.28` 复现：`StateBackend.write/awrite` 借 Pregel `CONFIG_KEY_SEND` 排队文件更新；`FilesystemMiddleware` 完成写入后返回 `ToolMessage`。外层 Middleware 在 `await handler()` **之后**改回错误回执，并不会撤销文件 State/Checkpoint 的更新。`reject_before` 未写入，`reject_after` 错误回执和持久文件并存；SDK 特征测试 PASS 只意味着阻断可稳定复现，**B2-A 仍 BLOCKED**。同进程 Profile 排除工具并集合并冲突也已证实。未有 B2 Graph、Aegra 重启或真实 Provider 验收。这个现象是 SDK 提交语义与原设计假设不一致，**不是已经证明 SDK 通用漏洞**。

当前不足：虽然两张 Deep Graph 已传入 `StateBackend()`，但 `HarnessProfile.excluded_tools` 隐藏 `ls/read_file/write_file/edit_file/glob/grep/delete/execute`；`PlanningBoundary` 实际只允许四 Reader + `write_todos`。**尚不存在模型可调用的虚拟文件笔记功能，也没有可靠的 Reader→虚拟材料→按需读取的 Context Offloading 证据。**

## 2. 目标、非目标与成功含义

### 本阶段目标

1. 为一个**新增、默认禁用、独立 Aegra 进程/配置中的实验 Graph**提供 SDK 原生 `StateBackend` 存储、最小可见虚拟文件工具和严格执行层权限校验：先实现有限的调查笔记写入和按需读取，再单独验收自动/受控 Offloading。
2. 虚拟笔记必须只能是**低信任模型工作材料**。准确诊断的权威来源仍是本轮原始 Reader ToolMessage（名称/Namespace/目标/UID、`tool_call_id`、成功/错误状态），绝不由文件内容或模型自己写的出处声明取代。
3. 验证保存/读取、状态边界、Checkpoint 恢复、取消/重连、Thread 之间隔离、跨 Human 轮次的旧笔记处理；失败时 Fail Closed，不调用额外越权工具。
4. 对比 B1 Planning ON 与 B2 Offloading ON 的**离线长输出/多轮合成**行为，包括模型可见上下文大小、消息/ID 完整性、文件占用、额外工具次数、估算输入大小。真实 Provider Token/质量/费用另行授权后才可能验证。
5. 复用 Deep Agents 0.7.28 的 SDK Middleware/Backend，不自建宿主机 FS 服务/HTTP API/长效 Store，不破坏正式 LangGraph 的 `context.py` / `context_summary.py`。

### 明确不做

- 不开启 `FilesystemBackend`（宿主磁盘）、`StoreBackend` 跨 Thread、`LocalShellBackend`/`execute`/Shell、`task`/Subagents、Skills、目录删除、任意 `edit_file`、命令或任何 Kubernetes 写接口。
- 不实施 Phase B3 Summary/Summarization 对照，不增新的 Context Summary LLM/第三方依赖，不替换现有 Reader 16 KiB 限制；不把 B2 说成“扩大 Reader 入口数据”，输入截断后无法由 Offloading 复原。
- 不接真实 Kubernetes，不修改生产 Graph、Repair/HITL、Incident Memory、已有认证/审批或正式环境 Compose，不自动导出 Langfuse Cloud。
- 不擅自运行 B1-R Pilot/Formal（真实 Provider）或修改已冻结 `eval/issue41-b1r/` Golden/Manifest/盲审表。

### 设计关键取舍

| 方案 | 收益 | 问题/代价 | 决定 |
| --- | --- | --- | --- |
| **独立 B2 实验 Graph + SDK FS Middleware + 支持的 Backend 写前校验薄适配** | 保留 SDK StateBackend/Checkpoint、可预防被拒绝写入进入状态 | 必须证实 SDK Backend 接口、跨并发配额及客户端状态边界 | **候选主方案；先 Spike，不可直接实施** |
| 直接在 B1 的 `deep_diagnosis_planning` 开启文件工具 | 改动少 | 破坏已验收 baseline；共享 Profile 排除项并集合并可能让工具意外禁用 | 不采用 |
| Host `FilesystemBackend` / Shell sandbox | 方便调试 | 越出单 Thread 受限存储边界、污染稳定设备、可能执行命令 | 不采用 |
| 手写 `file_read/write` 和另一套存储 | 容易完全定义工具 | 重复实现 Deep Agents 核心，不利于版本兼容 | 不采用 |
| 写后返回 ToolMessage error 作为回滚 | 看似能否决不合规文件 | 已被 PR #50 证明不会撤销 StateBackend 排队更新 | **禁止** |
| 立即启用默认自动大输出 eviction | 可能减少提示词负担 | 可能替换/缩略原始 ToolMessage，破坏证据与 Checkpoint | **先禁用或隔离验证，不直接全开** |

## 3. SDK 能力核对与 Profile 冲突（必须先证实）

依据官方 [Deep Agents Profiles](https://docs.langchain.com/oss/python/deepagents/profiles)、[FilesystemMiddleware](https://reference.langchain.com/python/deepagents/middleware/filesystem/FilesystemMiddleware) 与 [Backends](https://docs.langchain.com/oss/python/deepagents/backends)：
- `create_deep_agent` 默认包含必需的 Filesystem 基础 Middleware，即使 `StateBackend` 已传入，文件工具仍可被 Profile 排除；不能把 `backend=StateBackend()` 当成文件工具已授权的证据。
- `HarnessProfile.excluded_tools` 的注册合并为**集合并集**，现有 Phase A/B1 在 provider `openai`/`protocol_fake` 上注册了隐藏 `read_file`、`write_file` 等工具的 Profile；若与 B2 在**同一解释器进程**加载，即使 B2 Profile 不排除文件工具，工具也可能被早先 Profile 禁止。反向也必须防止 B2 给 Phase A/B1 重新暴露工具。
- 优先新建只加载 B2 Graph 的 `server/aegra.phase-b2.json` 与独立 Aegra 测试进程。各 Graph 进程不共享 Profile registry（以实际 SDK import/build 验证），不会将 B1 baseline 的工具清单变为五个以外。若需同进程 A/B 对比，应建立**真正受 SDK 支持的 profile 隔离方案**并证明两边有效工具集精确匹配；不可通过删除安全 `excluded_tools` 或绕过执行层凑数。
- 不能直接假设网页最新 SDK 参数适用于 `deepagents==0.7.28`。实施前在冻结 lockfile 环境用 `inspect.signature`、源码、实调用确认 `FilesystemMiddleware` 的 `tools` allowlist、`backend`/`state_schema`、`Command` 返回形态、eviction 配置、Middleware hook 顺序和可否禁用自动 evict。不能可靠实现精确最小权限时，**BLOCKED，先提交兼容性证据，不升级依赖或替换自研 FS**。
- `StateBackend` 的文件保存在 Graph State，经 Checkpoint 可在同一 Thread 恢复；它不等于外部磁盘、不默认跨 Thread。**不会降低 Checkpoint/数据库的原始数据占用**，尤其不能据此宣称减少持久化存储。真实可验证指标应是**送模上下文输入**是否降低、读取开销与状态大小是否受控。

## 4. 架构与职责

~~~text
独立 Aegra B2（默认不装入正式配置）
  └── deep_diagnosis_offload (new graph_id)
        ├── create_deep_agent(..., backend=StateBackend())
        ├── TodoListMiddleware（复用 B1 规划功能）
        ├── FilesystemMiddleware（SDK 原生，仅受限工具）
        │    └── ValidatedStateBackend?（待 Spike，校验在 StateBackend.awrite 之前）
        │         └── StateBackend → Pregel Send（只在允许后写入）
        ├── B2ToolBoundary
        │    ├── Kubernetes Reader: 4 × 原生 MCP → Phase A 参数/UID/ID 校验
        │    ├── Harness Todo: write_todos → SDK todos state
        │    └── Harness FS: read_file/write_file → SDK files state (/scratch/)
        ├── 目标 Pod 的本轮 Reader 证据守卫（必须继续生效）
        └── Aegra State / Checkpoint / SSE
              └── 回显状态与事件；前端只按 B1 的既有 Todo 展示
~~~

模型可见工具**目标恰为**：
`{pods_list_in_namespace, pods_get, events_list, pods_log, write_todos, read_file, write_file}`（7 项，B2-A）。`ls` 不是刚需，默认不暴露；`edit_file`、`glob`、`grep`、`delete`、`execute`、`task` 等始终不可见且执行前拒绝。若 SDK 最小工具集合不支持两个 FS 工具，优先检查模型可见集与执行层拦截是否可靠，无法保证时停止。**模型可见工具集合白名单不是唯一安全边界**；Middleware/执行层也要验证名称、参数、回执和副作用。

设计阶段不规定必须新建多层抽象：优先复用 B1 `PlanningBoundary` 中 Tool ID/计数/答复证据守卫的逻辑，用薄适配处理 `read_file/write_file` 两种新 Tool，而不是复制一份四 Reader 的 `mcp_client.py`，不直接改正式 `graph.py`。

### 4.1 File State 与访问契约

默认实验工作空间：`/scratch/`（POSIX 绝对虚拟路径，**不是宿主路径**）。建议在实施中以 SDK 实际路径参数名/规范化处理确认后冻结：

- 唯一允许文件路径示例：`/scratch/note-01.md` ～ `/scratch/note-06.md`。新文件必须归本轮已有允许列表/配额，禁止 `..`、`//`、`~`、相对路径、URL scheme、Unicode 同形/编码绕过、绝对 `/etc/...`、`/memories/`、`/artifacts/`、NULL 字节、符号链接或其它命名空间。
- 仅 UTF-8 纯文本笔记，单文件最多 **4 KiB**、最多 **6 文件**、总计最多 **24 KiB**，本轮最多 **3 次成功写**、**4 次读尝试**（先做候选默认值；按真实 SDK/API 可落地性做配置冻结并提供测试）。
- 内容中的 Pod log、Event、用户输入、历史回答及模型总结一律低信任；严禁 Secret、Token、凭据、kubeconfig、含真实环境数据或可能对外导出的敏感内容；合成哨兵碰撞要拒绝，未知/不合规内容 Fail Closed。不给笔记文本成为 System Prompt/Tool 认证来源的机会。
- **写入提交契约（本次修订，取代旧假设）**：所有会导致**拒绝**的安全判定必须在调用 SDK 原生 `StateBackend.write/awrite` **之前**完成：精确工具名与 Tool ID、路径规范化、内容/大小/敏感哨兵、文件数/总量、写入配额、覆盖/冲突规则、Thread/Run 隔离和 SDK 准备提交的数据。拒绝必须返回配对 `tool_call_id` 的错误且**不调用 SDK 写方法**，State 与 Checkpoint 中不得出现该次写入的更改。优先在 SDK **公开支持的 Backend 接口**使用一个小型 `ValidatedStateBackend` 委托给原生 `StateBackend`；具体接口、类型、是否有旁路都需先经 Spike 证实。
- **仅在全部检查通过之后提交**：通过写前校验才调用原生 Backend；一旦 SDK 接受并通过 Pregel Send 排队，不允许外层再用 `ToolMessage(status="error")` 冒充撤销。工具回执要区分“SDK 已接受写入”与“Checkpoint 已确认持久化”；需要在对应运行状态/Checkpoint 中做**只读事后核验**，事后核验失败只能停止/隔离该 Run 并报告未核验，不能假称回滚、补偿删除或修改历史快照。
- **异常/取消的明确语义**：合法且已被接受的写入可能在后续 Run 错误、取消或 Resume 后仍保留，这是受控工作状态，不是当前 Kubernetes 可信证据。**被拒绝、格式非法、越界或未经授权的写入绝不能持久化**；若业务未来要求“整个 Run 取消后所有写入都必须回滚”，须另行提出真正受 SDK 支持的事务机制设计，此阶段不声称可实现。
- **并发与客户端 State 是硬门槛**：必须证明共享文件总额/配额在并行 Tool Calls、同 Thread 并发 Run/多 Worker、重复 Tool Call ID 下不会出现 check-then-write TOCTOU。应用内 `asyncio.Lock` 不能证明跨进程串行；先评估并验证由 Aegra/SDK 支持的服务端串行化或拒绝同 Thread 并发写。客户端 `UpdateState/files` 若能绕过写前适配，必须在服务端限制/拒绝或把不受信任的客户端文件排除为不可用状态；不能只依赖 UI 隐藏。无法可靠封闭任一绕过路径 → **BLOCKED**，不得启动 B2 Graph。
- **Read 与 Write 分离**：`read_file` 先校验路径、预算与文件可见范围，任何来自文件的 ID/UID/“系统指令”均视为不可信材料，不能通过笔记绕过本轮 Reader 证据守卫。SDK 返回 `Command` / `ToolMessage` 的实际签名和错误含义由冻结版探针确证，不再错误假设文件写入返回可审核的 `Command.update`。
- 不复用 `todo` 的预算：Reader 6 次、Todo 5 次、模型决策 10 次沿用 B1 的上限，FS 读取/写入独立预算；不得仅靠 `len(ToolMessage)` 计数。额外 FS Tools 可能导致模型决策 10 次提前耗尽，先用 FakeModel 确认完整示例的可行性；若不够，单独提出有量化证据的预算设计调整，不在实施 PR 默默提升。
- 每次新 Human 回合**默认清空或隔离本轮工作区**，保留历史 Checkpoint 不变；`interrupt/resume` 应恢复同一回合未完任务与文件，不能把中断当成新轮。要通过真实 Aegra 协议实测同 Thread 新轮、分支/TimeTravel/旧生产 Thread 的可见性；在 API 无法安全区分“可信恢复文件”和“客户端通过 UpdateState 伪造文件”时，不能认定已实现服务端安全隔离。
- StateBackend 必须同一 Thread 读写一致，不允许跨 Thread 推断共享。不能清理不归本任务的 Postgres 记录；只允许清理测试命名空间中的独立 Thread/测试资源。

### 4.2 Reader 来源与证据可信边界（最重要）

严格区分三层：

| 层 | 内容 | 是否属于当前事实/证据 |
| --- | --- | --- |
| 原始 Reader ToolMessage | `call_tool` 生成、带 `tool_call_id`/目标/Namespace/UID/状态的本轮回执 | 仅满足现有验证逻辑时才可用于当前状态结论 |
| StateBackend 虚拟文件 | Agent 写入的摘录/推断/工作笔记；可以附本轮 `tool_call_id` 或 UID 字符串 | **不是可信原始证据**，仅作低信任搜索/记忆材料 |
| 给模型的临时视图/Offload Reference | 片段引用、分页内容、剩余可读文件路径 | 非当前事实；需回到本轮真实 Reader 校验 |

特别要求：
- **不允许** `FilesystemMiddleware` 对 `pods_get` 的原始 `ToolMessage.content` 自动替换成“已卸载至 /scratch/...”；这会破坏 PR #43 的当前 Pod UID/phase/Name 核验逻辑。`events_list`/`pods_log` 的长结果即使需要自动 offload，也必须先确保原本成对证据能够在 Checkpoint 中还原并且 Reader 的完成/错误状态不被新包装抹掉。
- 对 SDK 原生自动 Tool Result Eviction：**先通过真实 SDK 对合成大响应实测** Middleware 顺序、是否修改 State/Checkpoint 和对 `_target_evidence` 的影响。仅当存在受支持机制排除 `pods_get`、保留原 Reader 证明及完整 Tool ID 时才能选择性启用。否则本 B2-A 只启用手动笔记 `read_file/write_file`；自动 Offloading 的 Gate 继续 **BLOCKED/NOT RUN**，不得冒险修改原证明。
- `16 KiB` MCP 单次返回上限保持不变；超过入口上限的字节早已丢失，不能由笔记或 automatic eviction “找回来”。若要验证长上下文，使用**多次每条 ≤16 KiB** 的合成 Reader 消息组合，产生累计较长的模型输入，而非偷偷突破 Reader 限额。
- 可选 `note provenance` 只是显示/分析字段，必须由程序通过本轮原始 ToolMessage/Reader Attestation 的 ID 和时效查证，**不能因笔记中出现看似合法 ID/UID 而提升可信度**。如果实现查证需要大改正式 HMAC、Store 或 Checkpoint 语义，停止，留到独立设计。

### 4.3 Context Offloading 实际目标与状态

B2 分成两个实现 Gate（默认是**两个独立 Implementation PR**；不在本 Planning PR 实施）：

**B2-A：安全虚拟工作笔记**。仅在「B2-A Compatibility Spike」证明写前校验完整覆盖 SDK/Checkpoint/并发/客户端状态，且用户批准继续实施之后，才创建独立 `deep_diagnosis_offload` 实验 Graph、两个最小 FS Tools、路径/配额/UID 证据隔离/Checkpoint/取消/恢复。确保虚拟文件能被 Agent 写入、按需读回；保持原 B1 正式/实验行为不变。验证对大输入时的状态增长，**不宣称输入 Token 节省**。B2-A 完成后审查，无 P0/P1 才进入 B2-B。

**B2-B：模型输入 Context Offloading**。锁定 SDK v0.7.28 下检查内置 `FilesystemMiddleware` 的自动 eviction hook/阈值、对大 Human/ToolMessage 的影响；在**不改变可信 Reader 源数据**的前提下，选取合成多段 Event/Log 进行自动或显式引用→分页读取→恢复后的可验证路径。若无安全 SDK Hook（或自动 eviction 与 `pods_get` Guard 冲突），选择仅执行安全手动笔记对照，明确 `automatic_offloading=BLOCKED/NOT RUN`，不得手写“已卸载”字符串假称实现。必要时提出替代设计 Planning PR，等用户同意再调整实现方式。
- 评测指标：每轮模型可见序列估算字节/Token（估算标 `estimated`）、可核对的 SDK 逐段结果长度、Tool ID 配对、原始 Checkpoint/State 字节数、FS 文件大小及数量、额外工具/模型次数、失败率；无真实模型 Usage 时全部真实 Token/费用 **UNKNOWN**。
- B2/B1 用**同源冻结的合成长输入**配对（可以补新的 B2 长上下文 Fixture，但绝不修改 `eval/issue41-b1r` 已冻结内容或历史 Golden）；必须解释 B1/B2 Tool Count、Model Decision 预算及提示词差异，不能将 FakeModel 强制写文件造成的长度降低说成自主模型收益。
- B2-B 与 B3 Summary 互斥默认，绝不打开两个独立摘要器/上下文裁剪器；正式 Graph 的 `context.py` / `context_summary.py` 不改。是否与 B3 做三臂真实 LLM 对照由下一阶段另行设计/授权。

### 4.4 UI / SSE

B2 初期无需新文件浏览器或在线编辑器。现有 Web `PlanningTodos` 与 Aegra SSE、`agent_progress` 保持原功能；若需要看 offload 状态，只显示**固定词表、脱敏** `stored/referenced/retrieved/fallback` 及计数，不把文件内容、原始 Reader JSON、秘密或模型隐藏推理暴露到 Timeline。实施中先确认是否需要任何 Web Diff；没有就不要动 Web。

## 5. 测试覆盖与 Issue #41 Gate 映射

本文只映射 Issue #41，**不复制/替换它的权威 PASS 条件**。每项报告需写测试对象/环境/版本/命令/Result/证据位置/剩余风险，状态用 `PASS / FAIL / NOT RUN / BLOCKED / UNKNOWN`。

| Issue Gate | 本 B2 的验证方法与通过证据 |
| --- | --- |
| **B3 FS 隔离** | 7 工具精确可见/执行白名单、Reader+Todo/FS 分账、合法写/读、禁止路径（`..`、编码绕过、非 `/scratch`）、越界大小、空写/重复/并行冲突、Thread A/B 互不可见，删除/edit/Host FS/Shell/Subagent 皆拒绝；实际 StateBackend files 无宿主文件触达证据 |
| **B4 Context 协议** | 对多次 ≤16 KiB 原生 Mock Reader、长 Human History、多 Tool Calls、Tool ID 配对、重试/部分失败、Checkpoint/State/History、cancel/reconnect、TimeTravel 分支，逐条证明真实证据未被破坏；SDK 自动 eviction 对原始 ToolMessage 和 `_target_evidence` 的真实行为列证据，无法安全证明则不可 PASS |
| **B5 安全/记忆** | 同名不同 UID、历史 Healthy/当前 CrashLoop、日志 Prompt Injection 哨兵、跨 Namespace、伪造 `read_file` 返回及客户端预置 `files`/`AI/Tool`；文件不能变成可信当前证据、Repair/HITL/Memory 代码与行为不回归 |
| **B6 UI / Trace** | 本地 Aegra SSE/State 在 B2 显示的只有脱敏进度、旧 B1 Todo UI 无回归；没有浏览器或 Langfuse Cloud 手工测试就标 NOT RUN，严禁外传 |
| **B7 离线对照** | 新的只读合成长上下文至少：6 Reader 混合长 Event/Log、目标 `pods_get` 足量证据、无目标 Reader 403、UID 冲突、历史状态陈旧、读取丢失/文件超限；比较 B1/B2 估算输入长度、状态体积、额外 FS Calls、配对 ID 与错误退化；FakeModel 仅证明可用性，不证明真实质量 |
| **B9 工程交付** | 独立 Worktree、实际 SDK/lock、Ruff/pytest、相关 CI、隔离 Aegra FakeModel+Mock Reader Smoke（真实 Thread/Run/SSE/Checkpoint）、独立 Review/回归修复、可撤销实验 Graph、中文 Gate 报告、Draft Implementation PR、真实 Head SHA、无历史报告覆写 |

**B8 Real LLM + Mock MCP = NOT RUN**（无模型、请求数与费用预算授权）；B3 Summarization 的完整对照属于未批准 Phase B3。历史 Phase A A08=FAIL 与 Phase 3B B06=FAIL 保留原状态，不因 B2 的离线 PASS 修改。

如 Graph Checkpointer 合成测试重启后再连接，文件确实能恢复，并且撤销/旧轮逻辑无破坏，才将该项 Aegra 协议记 PASS。内存单测通过**不代表**重启恢复已验收。

## 6. 依赖、风险、停止条件与回退

**最大风险：SDK 自动 eviction 对 Reader ToolMessage 的改写。** 如果 `pods_get` 可信状态/UID/ID 因 Offloading 被修改、隐藏或“仿真引用”替代，立即 STOP（P1/P0），不允许靠 Prompt 或模型自述修复。

其余 STOP：
1. 模型可见或者可执行工具超出 7 项、意外 `Shell/execute/task/host FS`、未知路径/跨 Thread 文件访问、MCP Namespace 绕过、`Repair` 或写 K8s。
2. B2 重新注册的 `HarnessProfile` 影响既有 B1/Phase A 工具集；无法安全处理并集时保持独立进程，不牺牲原白名单。
3. **任何被拒绝的写入**进入 State/Checkpoint，或者校验之前已发生副作用；SDK 写入旁路、跨 Thread/进程并发超额、客户端 `UpdateState` 可绕过策略、非法/伪造文件被提升为可信证据。合法且已被接受的写入在后续 Run 失败/取消后留存不等于违反本次修订；若业务需要失败整体回滚，必须维持 BLOCKED 并重新设计。Checkpoint 提交失败、核验失败时不得虚报已持久化。
4. Provider 自动被调用、网络访问外传、费用不可控、实集群读取或写入、真实秘密/日志被写进实验 State/Trace。
5. 无法与锁定 v0.7.28 安全匹配的 API，或需要升级全部 Aegra/LangGraph、改生产 Graph/老 Thread/Checkpoint，必须 BLOCKED 回报用户决策。

**当前决策**：依据 PR #50 的兼容性证据，B2-A = **BLOCKED**，不能直接重复旧 AO 实施指令。仅允许先修订设计、做有限离线 Compatibility Spike，并根据独立 Gate 决定恢复与否。

**回退**：单独不加载 `server/aegra.phase-b2.json`，停用实验 B2 Graph 与专属容器；正式 `server/aegra.json`、B1 `server/aegra.phase-b1.json` 保持原样。B2 文件只存于独立实验 Thread 的 StateBackend，不能假装从 Checkpoint 删除它们；只清理本任务创建的资源和测试 Thread，不删除历史数据。含合成数据的实验日志私有保管、不得随 PR 提交敏感材料。

## 7. 实施阶段与 AO 交接

| 阶段 | 前置 | 工作 | 交付与 Gate |
| --- | --- | --- | --- |
| **Planning（当前）** | 审查 `main`、#41、PR #48、SDK 官方文档 | 编写 B2 设计、创建文档 PR | 仅设计，不跑业务测试、不合并 PR |
| **B2-A Compatibility Spike（修订新增）** | 本写入契约修订 PR **人工合并**至 main；以 PR #50 未合并证据的固定 SHA 核验真实探针 | 独立 Worktree，冻结 SDK，验证 `ValidatedStateBackend` 是否经**受支持**接口先完整校验再调用 SDK；覆盖合法/被拒绝写、Checkpoint、取消/异常、并发、客户端 State、Profile 隔离 | 仅兼容性测试/证据 Draft PR；不能注册可用 B2 Graph；结论为 GO 或 BLOCKED，**不能以已知 `reject_after` characterization PASS 代替功能 PASS** |
| **B2-A Virtual Notes** | Spike GO + 用户批准恢复实施 | 独立 Graph、两个文件工具、白名单/状态/限额/Checkpoint/安全负测 | Draft Implementation PR-A + B3/B5/B9 对应证据 + 独立 Reviewer + 用户 GO/NO-GO |
| **B2-B Context Offloading** | B2-A Gate 全部通过、用户另外明确同意该阶段 | SDK 大结果 eviction 安全性核对；只在安全前提下启用 Offloading、B1/B2 长输入对照 | 单独 Draft Implementation PR-B + B4/B7/B9 对应证据与失败轨迹 |
| **B3 / Real LLM** | 未来独立设计/费用授权 | 本阶段**不执行** | NOT RUN |

任务要求：
- `git fetch origin`，记录新 HEAD/SDK、检查并尊重用户现有工作树；Codex Worker 使用独立 Worktree，先读 `AGENTS.md`、Issue #41、此设计和 PR #48 验收线索。
- 所有 FakeModel/Synthetic Reader、isolated Aegra 的容器/端口/卷需独立所有权，可精准清理；不得操作真实 Kubernetes、稳定 Compose 或用户服务。
- 原系统、Phase A/B1、B1-R Prep 的测试与冻结 Manifest 必须仍通过；测试未执行标 NOT RUN、Mock 不能证明真实 LLM 或 K8s。
- AO 内部 Reviewer 与 GitHub 不同账号 Approval 分开陈述；有 P0/P1 需修复重新审查。未获合并授权不得 merge/close #41，也不得启动 B2-B。

**合并后 AO 短指令**（不将全文复制给 AO）：

> 仓库 `Vc-great/kube-triage-agent`；Issue `#41`；合并设计 `docs/plans/issue-41-deep-agents-phase-b2-context-offloading.md`；**只执行 B2-A Compatibility Spike**。读取 Draft PR #50（Head `6bba62305f0fae400c6c1c92a9c3a3b02884e14b`）的阻断证据；从最新 main 单独 Worktree 验证冻结 SDK 公开 Backend API 能否写前拒绝、并发限额、Checkpoint/取消以及客户端 UpdateState 旁路。仅 FakeModel/合成 State，提交探针与中文证据 Draft PR；不可启用 B2 Graph、不得继续 B2-A 实施/B2-B/B3 或真实模型/K8s；不能确认安全 → BLOCKED，不合并不关闭 #41。

## 8. 参考、状态与变更说明

- 官方文档：[Deep Agents Profiles](https://docs.langchain.com/oss/python/deepagents/profiles) · [Backends](https://docs.langchain.com/oss/python/deepagents/backends) · [FilesystemMiddleware](https://reference.langchain.com/python/deepagents/middleware/filesystem/FilesystemMiddleware) · [Changelog](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/CHANGELOG.md)
- 仓库真相：[AGENTS.md](../../AGENTS.md) · [SDD](../agent-workflow.md) · [B1 设计](issue-41-deep-agents-phase-b1.md) · [B1-R Prep 计划](issue-41-deep-agents-real-llm-eval.md) · [B1 验收](../issue41-phase-b1-implementation-validation.md)
- 2026-10-19：依据 `main=951c234` 完成原始 B2 设计；Phase B2 **尚未实施、未运行测试、没有新增权限授权**。
- 2026-10-19：针对 Draft PR #50 发现的 StateBackend 写后拒绝不回滚问题，依据 `main=e243d6abed6aa5ea2f5c37c85174a710bb2f5e26` 修订为写前完整校验 + 已接受写入保留 + 只读事后核验；引入 Compatibility Spike Gate。**尚未验证候选 Backend 适配可行性，不解除 BLOCKED，未实施代码、未授权 Provider/K8s。**
