# Issue #69 — Deep Agents Virtual Filesystem / Context Offloading：Demo-first V2 增量计划

> - 需求入口：[Issue #69](https://github.com/Vc-great/kube-triage-agent/issues/69)；关联总任务 [#41](https://github.com/Vc-great/kube-triage-agent/issues/41)。
> - **状态：Proposed / 仅设计，等待本轮 Planning PR 审阅并合入 main。** 本文不是已实现的事实或 Gate PASS。
> - 基线：2026-10-23 `main=1daea2b5291814c2fe9566691f514ce409d7d752`，最近合并 [Reviewer PR #88](https://github.com/Vc-great/kube-triage-agent/pull/88)；实施前重新 fetch。
> - 历史：[Planning #70](https://github.com/Vc-great/kube-triage-agent/pull/70)、[Revision A #71](https://github.com/Vc-great/kube-triage-agent/pull/71) **已合并**，不是“待合并”。旧 S1 Offloading 分页 **F3 FAIL / STOP**，历史记录保留于 Git 历史、#69 讨论与本文 `1.2；本版不把失败改为 PASS。
> - 版本：`deepagents==0.7.28`、`aegra-cli==0.10.8` 为已知冻结基线，Worker 必须以最新 `uv.lock` 与已安装 SDK 核实。
> - 本文 **`6 V2-A0～A5、V2-B0～B6 是唯一当前验收标准**；原旧计划 F0～F8 仅是历史版本，不与本版双重维护。
> - 用户 2026-10-23 决定：单用户 Demo、功能优先；**先交付可运行 Virtual Filesystem，再交付可靠自动 Offloading**。分别做 Implementation PR，B 遇阻不阻止 A 独立验收和交付。
> - 本次只批准设计和纯文档 Planning PR；规划合并后可开始 **Phase A**。**Phase B 在 A 合并并由用户批准推进后才实施**，不要在一个 Worker 中自动越级。

## 1. 当前代码、历史问题与用户价值

### 1.1 已有组件与真实缺口

- `server/src/kube_triage/deep_diagnosis.py` 已有原生 `create_deep_agent`、`StateBackend()` 和受控四 Reader MCP；HarnessProfile 当前隐藏 `ls/read_file/write_file/grep` 等 FS 工具。`deep_diagnosis_planning.py` 已有 `TodoListMiddleware / write_todos`、Reader/Todo 单轮预算。
- `server/aegra.phase-b1.json` 与 [#72 的 Reviewer Demo PR #88](https://github.com/Vc-great/kube-triage-agent/pull/88)、`scripts/skills_demo.py`/`scripts/review_demo.py` 提供隔离 Aegra/Web、FakeModel、合成 Mock MCP、PG Checkpoint、Tool Timeline 的可复用启动/测试结构；[#78](https://github.com/Vc-great/kube-triage-agent/issues/78) 已有可选 History/Evidence API，不重建。
- **尚未实现**：独立的 `deep_diagnosis_offload` Graph / Profile / Web Demo；模型能实际 `write_file('/notes/...')`、`read_file`、`ls`、`grep`；超阈值 Reader 结果自动 Offload 后按页完整回读。仅在 `build_graph` 传 `StateBackend()` **不等于**完成 Virtual Filesystem 功能。
- `server/src/kube_triage/deep_diagnosis_review.py` 经 #88 修复 Aegra 在 `graph.copy(update=...)` 时剥离受控包装器、`recursion_limit` 默认值覆盖问题。新 Graph 需核对真实 Aegra 加载，但**不要未经证明复制 Reviewer 的签记、nonce 和 Subagent 架构**。

### 1.2 不可抹去的 S1 失败反例

旧合成 `events_list` 返回 **100 行约 10,199 bytes**；Reader 现有外层 `json.dumps` 使它变成 **约 10,324 字符单行 JSON**。锁定 SDK 在实验 1,024 阈值下自动写 `/large_tool_results/reader`、缩短首次送模内容，但 `read_file(offset=0,limit=2)` 仅读到前 4,095 字符，`offset=1` 因文件只有一物理行报错，后段 `event-099` 不可达。历史专项为 12 PASS / 3 FAIL，**F3 FAIL**。

归因：SDK `read_file` 按文件物理行和输出长度预算分页；原文中的换行经过 JSON 转义，不是实际文件换行。**自动保存成功 ≠ 原文可完整回读**。本计划 B 阶段保留长文本正例、非零 offset、Unicode / 无换行负测，不能靠“只显示截断”“改阈值”“直接从 State 补尾”伪装通过。

## 2. 目标、分阶段非目标与既有边界

### 本期体验

- **Phase A — Model-managed Virtual Filesystem**：新隔离的合成 Demo 中，模型发出原生 `write_file('/notes/diagnosis.md', ...)`，随后由真实原生 `read_file / ls / grep` 查看自己保存的调查笔记。用户在已有网页 Tool Timeline 能看到真正的调用、返回及多轮效果。
- **Phase B — Automatic Context Offloading**：在 A 的基础上对**经原 Reader 校验后**的较长合成工具回执做有界可逆分页表示，交给原生 `FilesystemMiddleware` **自动**判断阈值、写 `/large_tool_results/`，模型只看到路径/预览，再用原生 `read_file(offset,limit)` 一页页读取完整回执。两项能力分开验证、分开 PR。
- 普通小结果保持直接可见或原样内联；对长结果，“压缩首次送模内容”只能代表输入视图变短，不宣称总 Token、费用或诊断准确率改善。真实效果后续在 [统一 QA #86](https://github.com/Vc-great/kube-triage-agent/issues/86) 验证。

### 本期刻意不做

- 原生 Summarization、#41 的生产级 State 写入口封闭、跨进程 nonce/签名认证、跨 Worker 原子配额/锁服务、真实模型 A/B、生产多用户隔离、任意中断点 Resume/Time Travel、跨 Thread 长期 Memory。
- 不引入 Host `FilesystemBackend`、LocalShell/`execute`、任意 `delete/edit_file/glob/task`、Repair、文件上传/管理平台、独立文件服务、新表/迁移、CLI 产品。不要为了“标准生产设计”强制增加新分布式锁或审批微服务。
- **不改变**正式 `agent`、Planning/Skills/Reviewer 实验 Graph，不触碰真实 Kubernetes 写入/删除、稳定环境资源、RBAC、Token、真实秘密或云端 Trace。
- 用户认可**仅限本机合成 Demo** 的已知 Aegra `update_thread_state → files` 旁路限制（[#68](https://github.com/Vc-great/kube-triage-agent/pull/68)）；不因此宣称 SDK 文件状态可抗恶意客户端任意篡改。它不能提升为权威 Kubernetes 证据。

### 保持的确定性边界

四个原生 Reader、`kube-triage-demo` Namespace、原有参数/UID/Tool Call ID 核对、8s、原 Reader 单结果 **16 KiB** 上限、Repair/HITL/Memory/Checkpointer 的既有行为必须保留。新虚拟文件内容是**模型工作笔记/非权威数据**，绝不能直接作为“新鲜真实 Pod 证据”或自动修复授权。只有 Mock/合成数据，隔离启动仅绑定本机/可信隧道，不对公网开放。

## 3. 最小可实施的技术方案

### 3.1 Graph、模式和工具集合

```mermaid
flowchart TD
    U[现有 Web / Tool Timeline] --> A[独立 Aegra Offload Profile]
    A --> G[原生 Deep Agent + Todo + FS + Reader]
    G --> F[FilesystemMiddleware + StateBackend]
    G --> T[四个合成 Reader MCP]
    F --> N[/notes 虚拟调查笔记]
    T --> V[现有 Reader 回执校验]
    V -->|Phase A / 短结果| I[直接给模型]
    V -->|Phase B / 长结果| J[有界可逆 JSONL ToolMessage]
    J --> O[SDK 原生自动 Offload]
    O --> C[(Thread Checkpoint files)]
    C -->|原生 read_file 分页| G
    G --> S[SSE 工具轨迹与中文回答]
    S --> U
```

- 新建独立 `deep_diagnosis_offload.py`、测试专用 Entry/Fake、`server/aegra.phase-offload.json` 和最小启动入口（优先复用 `scripts/skills_demo.py` 的进程监管/环境清洗）。**单个 opt-in Graph**，实验进程启动时选 `notes`（A）或 `offload`（B）模式；切模式必须新进程 + 新 Thread，不能迁移旧 Checkpoint。两阶段都保留同一正式 Reader 契约。
- 原生 `create_deep_agent` 已装配 FS，不能无意装出两个 `FilesystemMiddleware`。先在**锁定 wheel 的实际实例**验证 middleware 实例数、调用顺序、替换规则、`tools` 参数、`tool_token_limit_before_evict` 行为，记录捕获的真实模型可见工具集合；SDK 不符先做最小 PoC 纠正。
- 目标模型可见工具恰 **9 个**：四 Reader + `write_todos` + `ls`、`read_file`、`write_file`、`grep`。原生 SDK 提供文件工具，不另造同名 `@tool` 假冒。显示和执行层均不暴露 Shell、真实文件系统、`task`、`edit_file/delete`。
- Phase A **关闭自动大结果 Offload**（仅新实验 Graph，使用锁定 SDK 实证支持的配置；若 `None` 语义不符，明确选择不会在本期合成 Fixture 触发的安全实验阈值并实测）。Phase B 显式采用演示专用约 **1,024** 阈值，绝不修改正式 Graph；阈值是 SDK 的近似量，不声称精确 Token。
- 两模式均使用默认 **FakeModel + 合成 Mock MCP + 独立 PG**；真实模型无授权时不可借用本机 `.env` 自动启动。实验 Graph 一次只运行一个可控的新 Thread；同 Thread 普通连续 Run 允许，**并行多 Worker 对同一 Thread 写文件不在本期保证范围**，不能宣称生产级原子性。

### 3.2 Phase A：先交付模型主动笔记

- 使 SDK `write_file('/notes/...')` 将内容真实保存到 `StateBackend` 的 Thread Checkpoint，再由 `ls` 列目录、`read_file` 原样读取、`grep` 找到指定片段。FakeModel 应产生实际 Tool Call，由 SDK 完成写读；模拟“最终消息含一段笔记文字”不合格。
- 模型写路径仅限标准化的 `/notes/`，默认新 Thread 可写；读 `/notes/` 和（仅 B 模式自动产生的）`/large_tool_results/`。禁止模型写内部 Offload 路径、路径穿越、Host FS；文件预算独立于 Reader/Todo，沿用现有 6 Reader/5 Todo，建议新增显式文件工具最多 8 次/轮、写入最多 4 次/轮、每次 `write_file` UTF-8 ≤8 KiB；最终数字以实际 SDK 协议实测并在实现报告列明。
- **功能正确性验收**：正常 Thread 两轮写→读，刷新后在同一 Thread 仍能读取；新 Thread 不能读到另一个 Thread 的笔记；不存在路径清晰返回 error，UI 不显示“已保存”假成功。只要求本地单用户正常使用隔离，**不建设恶意客户端 State 注入对抗体系**。
- UI 只需复用已有工具卡片/Timeline 的 `write_file/read_file/ls/grep` 调用与回执、Todo 和中文结论，不新增文件浏览器、上传页面或独立 API。

### 3.3 Phase B：保留可逆回读的核心要求，削减复杂度

- 插入点只在新 Offload Graph 的 Reader 工具回执**已执行既有校验之后**，不改 `mcp_client.call_tool` 原始行为、旧四 Reader 对外名字、正式/Planning/Skills/Reviewer 图。对**成功且较长**的合成原始 ToolMessage 正文字节 `R` 做确定性表示，原始 `tool_call_id / name / status` 保持对应；工具失败保持 error，不造“成功的文件证据”。
- 采用上轮 Revision A 已论证的物理多行 `triage-reader-pages/v1` **JSONL**：首行 manifest（原 `tool_call_id/name/status`、`raw_bytes`、`raw_sha256`、`chunks`），后续数据行为有序 `seq/byte_offset/text`，原 `R` 按 **UTF-8 字符边界**分块。每条完成 JSON 转义后的物理行 ≤768 bytes（含 LF）；换行、Unicode 行分隔、反斜杠等编码后均不能破坏一行一记录。**在进入 SDK 之前保证整个派生表示仍不越过本项目原 Reader 16 KiB 边界**；超限只能明确失败或继续返回原有有界回执，不能默默删除尾部宣称完整。
- 是否“Offload”**完全由原生 SDK**在其 `FilesystemMiddleware` 收到长 ToolMessage 后判断、自动保存和返回路径/预览，**不能**在适配器中主动 `write_file`、拼假路径或直接用 State 获取原文替代模型回读。短结果应不触发 Offload。
- 冻结重放旧 S1 的 100 行 Events（含末条 `event-099`）以及无物理换行长字符串、多字节 Unicode、CR/LF、转义字符的合成案例。**必须仅从真实原生 `read_file(offset,limit)` 返回的模型可见 ToolMessage 多次读取**，按 seq/offset 还原，逐字节等于 `R`，并核对长度、SHA256、Call ID/name/status、页数及末页；此验收不可使用后端 `files` 全文作为补尾。State 原文只能作为独立存储一致性断言。
- 对 SDK `/large_tool_results/{normalized_call_id}` **可能覆盖同路径**的既有事实，限定 Demo 为隔离单 worker、每 Thread 不允许重叠进行中的 Offloading Run；历史已用或本批碰撞的规范化 ID 在调用前拒绝并返回可见 error，不覆盖已完成的旧文件引用。至少测试同 Thread 两轮重复 ID、规范化后碰撞、旧文件不变；不引入跨 Worker 分布式锁或声称任意并发原子性。**如果当前 Aegra 无法对受支持的运行范围避免同 Thread 重叠写，B STOP**，可保持 A 可用；不能用无锁“通常不撞”替代基本文件正确性。
- Offload 失败/被拒绝、页缺失、损坏、hash 不同、Reader 超时和 SDK 输出裁断时，用户只能看到 **不完整/未知**，而不是“完整证据”或“确证根因”。文件笔记不是受信的 Kubernetes 事实；模型是否正确理解其中内容属于未来真实模型效果测试。
- 运行前先固定 SDK 实测 `read_file(offset,limit)` 的输出上限与行计数；如果上游原生分页无法按规定完整回读，即 **V2-B2 FAIL/STOP**。禁止用调大阈值、替换原生 file tool、读取 State 补尾、故意跳过大结果来制造 PASS。

### 3.4 Aegra/Web、回退与集成边界

- 参考 #72 的 `graph.copy(update=...)` / config 兼容修复方式验证新图在真实 Aegra 中 `assistants/threads/runs/stream/state` 可用。Web 入口必须是真实 `ToolMessage` / SSE，不是纯 `MemorySaver` 或静态 HTML 演示。
- 按原启动器分配独立端口、Compose project/标签、PG 数据与进程归属；停止仅清理由本次启动的资源，不清共享卷。不触碰正式 `server/aegra.json`。
- Reader provenance 如开启 #78 的 `APP_EVIDENCE_ENABLED` / `APP_HISTORY_ENABLED`，复用原有 `reader_context`、`app_routes` 与 SQL，**不要新增一种“FS 文件即可信 Evidence”存储**；可选业务路由测试留到 [#86](https://github.com/Vc-great/kube-triage-agent/issues/86)。
- 停止独立 Demo 即回退，Phase A 已合并时 B 失败仅关闭 `offload` 模式，不回滚 A 的 `notes` 模式；不对旧 Thread 数据结构做迁移。
- 历史 #41/#68 发现的 `update_thread_state → files` 旁路仍**未修复**，不能部署公网或多用户、不能输入真实日志/Secret；旧 Summary/Recovery 的 STOP 和旧 #69 S1 FAIL 均保留为历史事实。

## 4. 取舍和风险

| 方案 | 体验收益 | 实现风险 | 决策 |
| --- | --- | --- | --- |
| **A 后 B、两个小 Implementation PR** | A 先可展示真实文件工具，B 继续增加自动 Offload | 两次 PR/CI，但 B 失败不影响 A | **采用** |
| 旧 F0–F8 一次性全做 | 理论验收更严格 | 跨 Worker 互斥/安全封闭投入大，功能迟迟不可展示 | 不采用 |
| 自建文件工具/自建 Offload 服务 | 协议容易定制 | 无法证明学习/使用的是 Deep Agents **原生**能力 | 不采用 |
| 只实现 A 不再做 B | 速度最快 | 无自动 Context Offloading，#69 目标不完整 | A 阶段可暂时验收，不能关闭 #69 |

**STOP（B 强制）**：数据无法完整回读、工具回执 ID 错配、文件覆盖旧引用、跨 Thread 读到别人的笔记、SDK 工具无法经 Aegra 运行、需要引入 Host FS/Shell/Repair、放宽 Reader 或修改稳定环境。这些是**功能正确性与现有边界**，不是额外生产级安全项目。发生 STOP 后留在 A，提交真实失败证据并请求是否另行修改 B 的设计，不得擅自改验收。

## 5. 实施顺序与 PR 交付

| 阶段 | 工作 | 交付方式 / 前置 |
| --- | --- | --- |
| **Planning V2（当前）** | 本 Markdown 与 #69 权威 Gate 更新 | 仅文档 PR，`Refs #69`；用户审阅并合入 main 后开始 A |
| **Phase A：Virtual Filesystem** | SDK 工具集、`/notes` 写读、独立 Aegra/Web、FakeModel+Mock、正常 Thread/刷新，基础回归 | **Implementation PR A**，`Refs #69`；通过 **V2-A0～A5** 即可独立审阅/合并，#69 保持 Open |
| **Phase B：Automatic Offloading** | 在已合并 A 的最新 main 上新增 `offload` 模式与 JSONL，复现并修复旧分页阻断；真实 SDK 回读、PG/HTTP、页面 | **Implementation PR B**，`Refs #69`；A 合并且用户批准继续后执行；完成 **V2-B0～B6** 后才考虑关闭 #69 |

Phase A 完成后不必等待 B 就可展示文件工具，也不要求再引入一个新 Planning PR；Phase B 若发生 SDK 原生限制以实际 FAIL/STOP 为准，保留 Phase A 代码与 Demo，不继续无止境重构。

## 6. 唯一权威验收矩阵（Demo-first V2）

| Gate | 阶段 | PASS 标准和真实证据 |
| --- | --- | --- |
| **V2-A0** | A 基线 | 最新 main/依赖/现有 Graph/#69/#41 实查；独立 Worktree + 测试环境，未修改正式/B1/Skills/Reviewer |
| **V2-A1** | A SDK 原生性 | 组装后恰一个 SDK 原生 FS Middleware，模型只见 4 Reader + Todo + `ls/read_file/write_file/grep`（9）；无 Shell/Repair/task/edit/delete；Fake 捕获和 SDK 工具对象记录 |
| **V2-A2** | A 文件功能 | FakeModel 实际发出 `write_file` 与 `read_file/ls/grep`，SDK StateBackend 真实持久；目录、UTF-8 正文、查找、路径失败与 Tool ID/结果配对，不能伪造回复 |
| **V2-A3** | A Thread/预算 | 同 Thread 正常两轮和刷新可读；新 Thread 无旧笔记；不存在/不允许路径失败可见；独立文件预算不影响 Reader/Todo |
| **V2-A4** | A Aegra/Web | 独立一键启动、真实 Aegra HTTP/SSE/PG、工具 Timeline 与结论、停止回退；不以 MemorySaver 或静态截图冒充服务运行，真人操作可后置 #86 |
| **V2-A5** | A 工程 | Ruff/pytest、适用 Web lint/build、CI、独立 Review、中文启动/清理/风险说明；PR A 只覆盖 A，`Refs #69`，不提前关闭 #69 |
| **V2-B0** | B 基线 | A 已合并且用户批准 B；新 main/独立 Worktree，无重复开发；旧 F3 失败正例仍可复现（旧路径） |
| **V2-B1** | B SDK 自动化 | offload 模式由原生 SDK **自动**保存并提供路径/预览；短结果内联、超阈值后首次送模变短；不开新 FS 实例、不改 Reader 边界/阈值绕过 |
| **V2-B2** | B **完整回读** | 100 行 Events、无换行、Unicode、尾部哨兵全部仅用原生 `read_file(offset,limit)` 分页，按 manifest 拼回每个 `R` UTF-8 原始字节、长度/hash/Call ID 等全部相等；无法完整恢复就是 FAIL |
| **V2-B3** | B 基本文件正确性 | 两轮旧 ID/规范化碰撞、缺页/篡改、并发同 Thread 禁入或可证明串行、Reader/文件错误：不覆盖旧引用、不声称完整；只承诺隔离单 worker Demo |
| **V2-B4** | B 真实协议/Web | Aegra + PG + SSE 真实自动 Offload 与文件按需读取有 Tool Call/Result、Checkpoint 保留、刷新后可读；不是适配器自写文件或直接取 State |
| **V2-B5** | B 兼容/退化 | Phase A 的 notes 不退化，正式/B1/Skills/Reviewer、Reader/Memory/HITL/Repair 回归；关闭 offload 后 A 仍可用，已知 #41 State 旁路仍未修复 |
| **V2-B6** | B 工程/交付 | 专项+全量测试、CI、独立 Review、中文逐 Gate/原失败对照/启动与回退，Implementation PR B `Refs #69`；真实模型/真实 K8s/真人 Web 未执行照实写 NOT RUN |

执行报告必须用 `PASS / FAIL / NOT RUN / BLOCKED / UNKNOWN`，每个 PASS 给命令、环境、测试输出和代码 SHA；不用纯 Mock 推断真实 Provider 或真实集群表现。旧 S1 12 PASS/3 FAIL 是历史实验，不是新 B 的通过结果。

## 7. 文件范围与交接

按最新代码缩小变更范围：

- 候选新增：`server/src/kube_triage/deep_diagnosis_offload.py`、`deep_diagnosis_offload_entry.py`、`deep_diagnosis_offload_fake.py`、`server/aegra.phase-offload.json`；必要时 `scripts/offload_demo.py` / Makefile。
- 既有复用：`deep_diagnosis.py` 的 `_reader_tools` / ReaderBoundary、`deep_diagnosis_planning.py` 的 Todo/预算、`scripts/skills_demo.py` 的启动器、Web Tool Timeline、Aegra 与 #78 的业务路由（可选）。
- A 专项/实际 HTTP 测试与 B JSONL/原生 read_file 字节恢复测试分别新增于 `server/tests/`，固定合成 Fixture；不放入真实日志/密钥。
- 每个 Implementation PR 最少有一份中文验收报告和重现步骤；合并后更新 `README.md`/`docs/architecture.md` 已实现能力，不提前把设计写成已交付。

### 交给 AO 的简短交接（本 Planning PR 合并后）

仓库 `Vc-great/kube-triage-agent`，Issue `#69`；权威设计 `docs/plans/issue-69-deepagents-filesystem-offloading-demo.md`。从最新 `origin/main` 新建 Worktree，读 `AGENTS.md` 与设计；**本轮仅 Phase A / V2-A0～A5**：原生 FS + StateBackend、受控虚拟笔记、合成 Mock/Fake、独立 Aegra/Web Tool Timeline，复用已实现的四 Reader/Planning 和 Demo 启动器。完成专项/CI/独立 Review，提交 Implementation PR A `Refs #69`，不自动进入 B、不关闭 Issue。失败 STOP 并报告证据。**Phase B** 在 A 合并且再次获用户批准后独立执行；必须用原生 `read_file` 完整回读旧长文本反例，保持字节校验，不能以局部回读、调大阈值或从 State 补尾替代。无真实 Kubernetes 写入/付费模型/敏感外传/稳定环境改动。
