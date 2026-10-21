# Issue #69：Deep Agents Filesystem / Context Offloading 隔离 Web Demo 设计

> - 需求：[Issue #69](https://github.com/Vc-great/kube-triage-agent/issues/69)（需求范围入口）；相关历史：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)、[P0 Demo PR #66](https://github.com/Vc-great/kube-triage-agent/pull/66)、[P1 State STOP PR #68](https://github.com/Vc-great/kube-triage-agent/pull/68)。
> - 状态：**Revision A / Proposed（纯文档 Planning PR）**。原计划已由 [PR #70](https://github.com/Vc-great/kube-triage-agent/pull/70) 合并；S1 随后因 F3 回读失败 STOP。本修订尚未获审阅/合并，不代表功能已实现或 F3 已通过。
> - 本修订基线：2026-10-21 重新 `git fetch origin`，`origin/main=6dbbc07ee1ac6a8e8545dfce59484623dd8dc93d`（PR #70）；当前无开放 PR。原计划基线 `c666fcc` 为历史记录。发布/实施前仍需重新核对。
> - 锁定版本：`deepagents==0.7.28`（`server/pyproject.toml`）、`aegra-cli==0.10.8`，以现有 `uv.lock` 和实际安装 SDK 复核为准。
> - **唯一权威验收矩阵是本文第 6 节**。Issue #69 只指向本文，不复制 Gate。Issue #41 的历史 B3/B5/B8 及 STOP 继续有效；本 Demo PASS 不能重标 #41 为 PASS。
> - 执行授权：用户选择 A，**本轮只修订计划并提交纯文档 Planning PR**。实施保持 **S1 STOP**；本修订经人工审阅、合并进 main 前，不继续实现或进入 S2。合并后先从 S1 重验 F0–F3，不能沿用旧 PoC 的局部通过结论直接进入 S2。不自动合并、不关闭 #69。用户已明确不将原生 Summarization / Aegra State 写入口封闭作为本 Demo 的前置需求，**不等同于同意打开真实集群或公开服务**。

## 1. 背景、已实现和缺口

用户目标：在现有浏览器 Demo 中真正体验 Deep Agents 原生 Virtual Filesystem 与 Context Offloading，并通过可核对的 Tool Call / State / Checkpoint 证据知道“文件何时写入、何时读取、为何缩短模型上下文”。

当前已实现（不是本计划新增）：
- `server/src/kube_triage/deep_diagnosis.py`：真实 `create_deep_agent`、`StateBackend()`、四个严格 Reader；`HarnessProfile.excluded_tools` 及 `ReaderBoundary` 将文件、Shell、Subagent 等全部挡住；返回证据有 Namespace/UID/Tool ID 检查及 16 KiB 单结果上限。
- `server/src/kube_triage/deep_diagnosis_planning.py`：原生 `TodoListMiddleware`、`write_todos`、`PlanningBoundary`，当前模型工具精确集合为“四 Reader + Todo”；现有预算：10 次模型决策、6 次 Reader、5 次 Todo 写入。
- `server/aegra.phase-b1.json` 和 `make dev-deep-demo`：隔离 Aegra 多 Graph、合成 Mock Reader + 原有真实 LLM 路径、前端 Todo/Tool Timeline/SSE/Thread/Checkpoint，默认正式 `server/aegra.json` 仅有 `agent`。
- `server/tests/test_deep_diagnosis_summary_spike.py` 和 `docs/issue41-p1-summary-spike-validation.md`：证明客户端可从 Aegra `update_thread_state` 更新 `files`，不经 Middleware；原生 Summary S1 BLOCKED，未修复。
- 现有 Reader 每次最多 16 KiB；因此**不能**假设一条工具结果自然超过 Deep Agents 原生默认 20,000 Tokens 离线阈值。

当前尚无：对模型开放的 `write_file/read_file`；可回读的大结果 Offloading 演示；文件与 Todo/Reader 分别计预算；浏览器中可见的文件工具事件。本计划不把“仅传入 StateBackend”写成“Filesystem 已完成”。

### 1.1 已发生的 S1 STOP（不是本修订的 PASS 证据）

在上述 `6dbbc07` 基线和锁定环境（Python 3.13.14、Deep Agents 0.7.28、Aegra 0.10.8）中，FakeModel + 合成 MCP 复现：100 行 Events 原文 10,199 bytes，经现有 `_reader_tools()` 的 `json.dumps` 封装后为 **10,324 字符的单行 JSON**。SDK 在阈值 1,024 下自动保存 `/large_tool_results/reader`，模型预览缩至 1,588 字符；但原生 `read_file(offset=0,limit=2)` 只返回 4,095 字符，`status=success` 仍缺末尾 event-099；`offset=1,limit=1` 返回 `status=error` 和 `Error: Line offset 1 exceeds file length (1 lines)`。直接用原生 SDK 和已有 Reader 封装、去掉新增 Boundary 的最小复现得到相同结果。

原因：JSON 字符串里的原文换行被转义；SDK 按**原始物理行**分页，并在读取输出上复用近似 `4 × 1024` 字符预算。文件保存完整、模型输入缩短都不等于完整回读；单个超长行的剩余部分不能靠增加行 offset 恢复。原实现路线 **F3 FAIL**，仍保留为回归反例，不以本修订覆盖历史失败。专项试验为 12 PASS / 3 FAIL；这不构成完整 F0–F8 验收。本修订的分页方案尚未实现、未通过任何 SDK/FakeModel/Web 测试。

本地合成详细记录在 AO 会话 `kube-triage-agent-18` 的非 PR artifact `issue-69-s1-stop.md`；以上数字与原始错误足以在仓库计划中识别该失败，不要求其他机器访问个人绝对路径。复现顺序：现有四 Reader 封装接合成 Mock → events_list 返回上述 100 行 → 原生 FS 阈值 1024 自动保存 → 原生 read_file 连续读取 offset 0 和 1；不需要真实 Provider、集群或额外服务。


## 2. 范围、取舍与已知风险接受

### In Scope

1. 新增**独立 opt-in 的 offload 实验 Graph 和启动 Profile**；不替换 P0 Planning ON/OFF，沿用现有 Web 和合成 Mock Reader 运行链路。
2. 复用锁定 SDK 的 **原生** `FilesystemMiddleware` + `StateBackend`，开放最小工具集合 `ls`、`read_file`、`write_file`、`grep`（最终以 SDK assembled tool list 证明，不自行创建同名替代工具）。
3. **区分两条能力**：
   - A. *Model-managed virtual notes*：LLM 自行调用 `write_file('/notes/...')` 保存非权威诊断笔记，再用 `read_file`/`grep` 回读。
   - B. *SDK automatic tool-result offloading*：当合成 Reader 的某条 `ToolMessage` 超过实验阈值时，由 SDK 自动存入 `/large_tool_results/` 等内部路径；模型看到预览/文件引用，按需 `read_file(offset,limit)` 回读。**该阈值只针对新 Graph 生效**。
4. 仅在隔离 Graph 引入第 3.3 节的可逆分页结果表示；原始 Reader 校验、正式/P0 工具封装和 SDK 均不变。以合成 Fixture 测短/长 ToolMessage、Checkpoint 同 Thread 恢复、另一个 Thread 隔离、并发/取消/超时负测；现有 SSE/Timeline 可见 file tools 的调用与返回（不要求独立文件管理页）。
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
    K --> V[Validate raw paired Reader receipt]
    V --> E[Demo-only reversible JSONL representation]
    E -->|small ToolMessage| L[Model context: inline result]
    E -->|over demo threshold| O[SDK native large_tool_results offload]
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

推荐基于 `FilesystemMiddleware(backend=StateBackend(), tools=['ls','read_file','write_file','grep'], tool_token_limit_before_evict=1024)` 做独立实验；必须用实际安装 0.7.28 API 复核形参及阈值；**1,024 是本修订继续锁定的 Demo 实验阈值而不是生产值**。不能通过提高或关闭此阈值、替换原生 read_file 或忽略截断绕过 F3；SDK 对字符的近似计数也不是实测 tokenizer token 数。不启动 Summary Middleware：保持新 Graph 显式排除 `SummarizationMiddleware`，用 assembled stack 验证。禁止 `execute` 和任何宿主盘 Backend。

### 3.2 模型与工具执行白名单

新 Graph 的**精确目标工具集合**是四 Reader + `write_todos` + `ls` + `read_file` + `write_file` + `grep`（合计 9）。不允许 `task`、`edit_file`、`delete`、`glob`、`execute`、`shell`、`apply_patch` 或任何 Repair。模型可见工具集合和执行处理必须一致，不能只靠 Prompt 隐藏。

执行预算独立统计，候选上限：每轮模型决策 12、Reader 6、Todo 写入 5、**模型显式文件工具调用合计 8（其中写入最多 4）**；SDK 内部自动 Offloading 不消耗模型文件调用次数，但其失败需要可观察。对多 Tool Calls 同一回合、重复 ID、Call ID 与回执错配、并发文件写入，以执行前验证为准；不可依赖执行后返回 `error` 来撤销已经提交的 State。任一未知文件工具直接拒绝。

文件路径规则：
- 模型写入只允许 `/notes/` 下归一化的相对文件（绝对虚拟路径）；拒绝路径穿越、路径别名和对内部 `/large_tool_results/`、`/conversation_history/` 等路径的模型写入。
- 模型可读取 `/notes/` 与 SDK 自动 Offload 结果所在内部路径；禁止读取未知文件路径、跨 Thread 状态，以及任何宿主机路径。读写路径校验放在**执行层**，优先使用 SDK 公开 `permissions` 与 `FilesystemPermission`（若锁定 SDK 提供）；必要时按现有 Boundary 在 handler 前验证，而非工具执行后拒绝。
- 单条模型写入 `content` 最多建议 8 KiB UTF-8；`read_file` 的 offset/limit 有合理范围（例如 limit ≤100 行），单轮调用计数控制。**不宣称有已经证明的跨并发原子总配额**；如需多轮全 Thread 文件数/总量上限，必须验证预写原子性，否则将其列为残留限制，不静默声明“64 KiB 硬上限”。
- SDK 自动写入内部文件路径不应被模型 `write_file` 覆盖；验证 built-in permission 对 internal offload 的行为，不能让权限限制误阻断 SDK 正常 offload。
- 原始 ToolMessage 和模型调用结果的 `tool_call_id`、`name`、`status` 成对；模型读到的预览/笔记不可作为新的 `pods_get` 成功回执。

### 3.3 Offloading 触发、可逆分页表示与证据契约（Revision A）

**仍是两条能力：**主动 `write_file('/notes/...')` 只证明虚拟笔记；自动 Offloading 必须由真实 SDK 在 Reader ToolMessage 返回后触发，不能由模型/适配器主动写 `/large_tool_results/`，也不把“将长结果改成摘要”算作完整保存。

#### 3.3.1 唯一插入位置与数据顺序

仅新 `deep_diagnosis_offload` Graph 使用一个有界序列化适配器，复用现有四 Reader 工具的真实调用及校验，不添加第十个工具，不修改原生 FS 工具或安装的 SDK：

1. 校验本轮真实模型发出的 Reader Call：工具名、Namespace、参数、唯一 ID、当前用户轮次和 Reader 预算；调用现有 `mcp_client.call_tool`。校验原始回执的 `ok/result/error_type`，以及目标 Pod 的 Namespace/name/UID、回执 `name/tool_call_id/status` 配对。
2. 保留原始回执 `R`：现有封装实际会返回的 **UTF-8 ToolMessage 正文字节**，包括 JSON 键顺序、转义、空白。先完成原始校验，再派生分页表示，不能拿表示中的自报字段代替校验；不去尾、不改换行、不概括内容。错误/拒绝回执保持错误语义，不伪装为成功数据。
3. 成功且非空的 R 确定性编码为下面的 `triage-reader-pages/v1` 文本；保留外层 ToolMessage 原来的 `name`、`tool_call_id`、`status`，只改变新 Graph 的 `content` 表示。短/长结果采用同一版本的表示；表示是否超过阈值由 SDK 决定。
4. **原生** FilesystemMiddleware 接收该 ToolMessage，自己判断是否自动保存、生成路径和 preview；自动写入不计显式文件工具预算。适配器不写文件、不生成冒充 SDK 的引用，也不自行把正文换成路径。
5. 模型只通过现有原生 `read_file(offset,limit)` 获取文件记录；完整性测试只能从这些模型可见回执还原，不能在测试中直接读取 State 全文“补尾”。Checkpoint 文件可用于另行断言保存一致性，不能代替回读。

#### 3.3.2 拟定线格式：有界 JSONL，按原始字节偏移重组

一个表示由 **1 行 manifest + N 行 data** 组成，物理行分隔符固定 LF、末尾不额外添加 LF。每一行是独立合法 JSON；使用 `ensure_ascii=False`，紧凑分隔符。字符串内的 CR/LF/反斜杠/引号保持 JSON 转义，并显式转义所有会被 Python `splitlines()` 识别的其他分隔字符（例如 U+0085、U+2028、U+2029），保证一条 JSON 记录恰是一条 SDK 原始行。

manifest 的固定字段：`format="triage-reader-pages/v1"`、原 `tool_call_id`、`name`、`status`、`raw_bytes`、`raw_sha256`（R 的 SHA-256）、`chunks`。data 的固定字段：`seq`（从 0 连续编号）、`byte_offset`（R 的 UTF-8 起始偏移）、`text`（R 的连续文本片段）。例如（仅展示字段形状，不是可验收 Fixture，digest/长度需由实际编码计算）：

```text
{"format":"triage-reader-pages/v1","tool_call_id":"reader","name":"events_list","status":"success","raw_bytes":123,"raw_sha256":"<actual sha256>","chunks":2}
{"seq":0,"byte_offset":0,"text":"<R 的第一段，包括实际 JSON 转义>"}
{"seq":1,"byte_offset":64,"text":"<R 的下一段>"}
```

编码器按 **UTF-8 码点边界**贪心选择片段，使每条 data 记录在完成 JSON 转义后含 LF 的编码长度 **≤768 bytes**；不能先按原文长度切片，再假定序列化后的行仍有界。manifest 含 LF 同样 **≤768 bytes**；过长 ID/元数据导致超限时显式拒绝，不能截短 ID。`byte_offset` 根据原始 R 计算，不能用转义后字符数代替。格式定义不要求原始数据恰为多行，必须支持单个无换行长字符串、Unicode 和 CRLF。

解码只取回读输出中的**完整源行记录**，排除 SDK 的行号/窗口头/截断提示；解析 manifest 与 data，验证精确字段集合、版本、字段类型、连续 seq、UTF-8 byte_offset、chunks、raw_bytes 和 raw_sha256。按 seq 拼接 text，再编码 UTF-8 必须与 R **逐字节相等**；JSON 语义相等或只匹配摘要/首尾标记不够。再解析重建的原始 envelope，校验 `ok/result` 及目标 Pod 的 Namespace/name/UID 未变。缺行、部分行、错序、重叠、重复、不同 ID 混入、digest/长度不符都属于**不完整/不匹配**，不得宣称已完整读取。

这不是新文件读工具或可信存储协议。SHA-256 仅用于对照本次真实 Reader 的原始 R 检测表示/重组错误；文件自带 hash 可被一并伪造，**不提供来源认证**，不修复 Aegra `files` State 旁路。

#### 3.3.3 16 KiB、读取页大小与现有预算

原四 Reader 的工具/Namespace/参数/UID 与现有结果限制不动。当前实现以 `MAX_RESULT_CHARS=16*1024` 截字符，不能把它虚称为已验证的 UTF-8 字节硬上限；本隔离 Graph 在此基础上**额外收紧**：原始 result、原始 envelope R 和最终 JSONL 表示均须分别满足 **UTF-8 ≤16,384 bytes**，同时保留原有字符上限。原文已有 `[结果已截断]` 标记的回执不作为“完整原始结果”正例。

表示开销可能使本来小于 Reader 上限的结果超限；这不是扩大 Reader 上限的理由。出现该情况须返回配对的表示超限错误，**不省略数据、不部分编码、不 Offload 部分内容、不以失败样本计 F3 正例**。此限制和错误必须在使用/验收文档中披露；若实际需求要求这些超限样本也成功，先 STOP 并重新审阅表示设计，不能静默缩小验收输入或提高 16 KiB。F3 的长正例至少包含原失败的 100 行/10,199 bytes 合成结果，不能靠换成很短文本或拒绝所有长结果过关。

分页建议 `read_file(offset=0,limit=4)`，随后按 SDK **实际完整显示**的结束行/next offset 递增；不能简单做 `offset += 请求的 limit`，否则 SDK 裁掉尾行时会跳读。4 条有界记录含行号和窗口提示应低于 `4*1024` 字符，**仍须用锁定 SDK 实测证明**；如 SDK 因元数据额外开销裁页，只接受完整行并按真实 next offset 继续；任何单行出现 `truncated mid-line` 仍 FAIL/STOP。不要编写去除正文任意数字前缀的宽松正则；SDK 包装解析器要有原始回执 Fixture 和针对性负测，不能误删原文。

显式文件调用仍每轮最多 8 次、其中 write_file 最多 4 次；模型决策仍 12、Reader 6、Todo 5。JSONL 总大小≤16 KiB 且每行≤768 bytes **本身不保证总行数**，不能据此声称一定 8 次读完。编码后必须核算完整遍历所需页数，S1 正例要证明在本轮剩余预算内完成；超预算必须停止并报告未完成。完整回读专项可独立一个用户轮次，不与笔记/ls/grep 演示混算；若某个需验收的长正例无法在原预算完整回读，F3 继续 FAIL 并反馈设计，不通过扩大预算或多轮暗中接力冒充通过。

#### 3.3.4 Reader 证据配对与信任隔离

- 在适配前拒绝缺失/重复 ID、name/ID 错配、失败状态/空正文、跨 Namespace、非法 Pod 参数、错误 UID 等；非本轮执行产生的 AI/Tool 回执不得作为适配输入。预算检查在执行前，不在 State 写入后撤销。
- 自动 Offload 的外层回执仍对应原来的 Reader Call；manifest 必须与实际配对的 Call 和 R 一致。read_file 回执只配自己的文件 Call ID，**不能重新命名成 pods_get 或生成一条新的成功 Reader 回执**。
- 最终诊断仍使用现有当前轮次 Reader 证据规则，不能直接让 baseline 的 JSON 验证器把 JSONL/preview 当成功 envelope；仅在隔离模块做表示层处理。对照 R 的验证须来自本轮真实 Reader handler，不能相信客户端注入的 manifest、`files` 或新增 State 证据字段。
- 不以新增全局/Graph 实例缓存保存 R 跨请求使用，也不将客户端可写 State 当认证缓存。若原始回执经过编码/Offload 后无法由现有最终证据链核验，本轮结果保持“当前状态与根因未核验”；不得从文件/笔记重建肯定诊断来凑展示效果。需要扩展肯定证据链时另行审阅，不能顺带修复/绕过 #41 的认证问题。
- 完整读取这个**缓存表示**不等于 Kubernetes 当前状态核验，也不自动完成 Todos；外部 State 更新可同时伪造数据和 digest 的已知风险继续保留。Thread 隔离、取消、失败与并发必须从现有 Aegra/Checkpoint 实际行为单独验证。

#### 3.3.5 完整回读测试（待实施，不预填 PASS）

以下是第 6 节 F3 的测试证据要求，不新增第二套 Gate：

1. 保留旧“单行 JSON + 原生 FS”复现，断言 10,324 字符/1 行、读取缺尾和 offset=1 错误，作为历史行为特征测试；其执行成功不代表新 F3 PASS。
2. 短合成 Reader 经同一编码器后仍低于阈值，完整内联、无 large_tool_results 文件；解码等于原始 R。不能用跳过适配的另一条伪造 Reader 路径作对照。
3. 原失败的 100 行/10,199 bytes Events 和**单个无换行的长 result**分别经真实 Reader 封装与适配器，再由 SDK 自动 Offload。断言表示>4,096字符且原始/派生各项≤16 KiB；若所选内容不满足这些前提，不能把测试计正例。
4. FakeModel 明确先消费 SDK preview，再用原生 read_file 从 offset=0 到 EOF 完整遍历；必须包含**非零 offset**读取和中/尾部非 preview 内容。捕获每次模型可见输入/输出的 ID、name、status、实际窗口、next offset、完整记录集合与调用计数；逐字节拼回 R，核对全部内容而非只断言 event-099 存在。不得从 result['files'] 补充任何缺失片段。
5. 至少覆盖引号、反斜杠、空行、CRLF、中文/多字节字符、Unicode 行分隔符、原文伪造 SDK 行号/截断提示及完整度声明；编码/解码必须字节可逆，无吞行、重复或码点断裂。模型输入的**首次 Reader 回执**须比完整 JSONL 和原始 R 都更短，按实际字节/字符数分别报告，不能把多次分页累计输入声称为总体节省。
6. 破坏一个分片、删除中/尾页、重复 seq、混入另一工具或 Thread 的 manifest、篡改 ID/UID/hash、制造 SDK 页截断/错配/预算不足，必须失败或保持证据不完整，不得输出“完整读取/根因已证实”。缺文件/Backend 读写失败、Checkpoint 恢复与 Thread 隔离同时按 F4/F5 验证。
7. 原始 result/R/JSONL 的 UTF-8 大小边界、派生表示开销溢出、manifest/单行大小边界均须有正/负测，完整长正例不能因拒绝而计 PASS。若任一必要长正例或证据配对规则无法成立，仍 STOP 于 S1，不进入 S2。

关闭 Summary 后，单条工具结果的 Offloading 仍不承诺任意长历史无限压缩；JSONL 会增加 Checkpoint 字节数，必须报告表示开销和读取次数，不引入额外存储组件。上述序列化/窗口解析与原始证据规则的组合尚未验证，Planning PR 合并不是功能验收结果。

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

**回退**：新表示只用于新 offload Graph，不迁移旧 Thread、不改写历史文件；撤销修订实现时停用该入口而不改变正式/P0 回执。原完整性失败记录保留。不运行 `make dev-deep-offload-demo` / 移除独立 `aegra.phase-p2-offload.json` Graph 即回到 P0；正式 `agent` 和 P0 两 Graph/Checkpoint、Repair/HITL/Memory/SSE 保持不变；不删除共享数据库卷和历史证据。

**STOP**：SDK API 或实际 assembled middleware 与设计假设冲突且无法轻量修正；需要放开主/正式 Graph、接真实 K8s、放宽 Reader、引入 Shell/Host FS 或公开 Aegra；能从其他 Thread 读取到文件；文件回读绕开 ReaderBoundary 导致错误“已验证”结论；敏感数据外传、付费调用超授权、破坏已有 Checkpoint/CI。不得以 Demo 为由消除上述 STOP。

## 5. 阶段实施计划

| 阶段 | 实施范围 | 交付 | 是否能继续 |
| --- | --- | --- | --- |
| **Planning 修订 A（当前）** | 仅本文：失败事实、可逆分页表示与原文/证据契约 | 纯文档 Planning PR，Refs #69；原 PoC 不发布 | 本修订经人工审阅并合并 main；此前保持 S1 STOP |
| **S1：锁定 SDK / FakeModel PoC** | 新进程隔离 Profile、原生 FS 唯一实例、9 工具清单、1,024 阈值、可逆 JSONL 与原始回执配对、短/长合成 ToolMessage、完整回读/预算/Thread 限制 | 从 S1 重验的专项测试与证据（可在同一实施 PR 逐阶段提交） | Gate F0–F3 PASS 才进 S2 |
| **S2：隔离 Aegra + Web Demo** | 新 Graph + 入口 + Make Profile + 最小 Timeline 映射；只起本任务独立服务和合成 Mock | 可用的 `make dev-deep-offload-demo` + Aegra State/SSE/Checkpoint/浏览器证据 | Gate F4–F6 PASS 才进 S3 |
| **S3：工程收口 / 审查** | Ruff/pytest/Web lint-build/CI、中文手册和残留风险、独立 AO Review | 1 个 Implementation PR（Refs #69），记录 F0–F8 状态 | 用户最后决定合并；未满足最终 Gate 不关闭 Issue |

优先所有行为离线 FakeModel 验证，再用既有可获授权的 Provider 路径做**少量合成 Mock** Smoke；真实模型调用不是进入 S2 的前置条件。若须付费模型做浏览器验证：先取得该轮请求范围/成本明确授权，不能仅依靠现有 .env 中有 Key。不能实时证明调用上限时，真实模型 Smoke 维持 `NOT RUN`。

Worker 按 `AGENTS.md`：fetch 最新 main、独立 Worktree、先验证当前代码和未合并 PR、遵守各阶段 STOP；纯合成数据；先执行较小专项测试再全量回归；每个 Gate 标 PASS / FAIL / NOT RUN / BLOCKED / UNKNOWN 并贴证据，绝不能把 Mock 判作真实 K8s PASS。

## 6. 权威验收 Gate（仅此处维护）

| Gate | 验证对象 / 环境 | PASS 条件与实际证据要求 |
| --- | --- | --- |
| **F0** | 基线/依赖 | 记录实际 `origin/main`、SDK 0.7.28、Aegra 0.10.8、原有 P0/正式 Graph 未变，仓库已无冲突实施 PR；附命令/版本/实际路径 |
| **F1** | 新 Graph 工具/中间件 | assembled stack 仅 1 个原生 `FilesystemMiddleware`，明确未启 Summary；模型工具**恰 9 个**，Shell/Repair/task/delete/edit/glob 不可见且执行拒绝；P0 严格旧名单保留；附 FakeModel 捕获 |
| **F2** | 原生虚拟文件工具 | `write_file('/notes/...')` 写入，`ls/read_file/grep` 可读取 SDK `StateBackend` 实际文件；未知路径/穿越/内部目录模型写入/过大内容/超预算在写入**前**拒绝，拒绝后无文件增量；模型回执 ID 成对；新表示不得扩大任何文件执行权限 |
| **F3** | **自动** Offloading + 完整可逆回读 | 保持原 Reader 边界及第 3.3 节原始/派生 UTF-8 ≤16 KiB，阈值 1024 不变；短表示不创建 Offload。原失败的长合成 Reader 与无换行长文本正例**由 SDK 自动**保存 JSONL，ToolMessage 有路径+预览，首次模型输入比原始 R/完整表示都短；仅用原生 `read_file(offset,limit)` 在原预算内遍历全部页（含非零 offset），从实际回执逐字节重建 R、校验长度/hash/全部分片及 Call ID/name/status/原始 envelope，Checkpoint 保存一致；损坏/缺页/混配/截断/溢出不得宣称完整。执行第 3.3.5 节全量正/负测；不得从 State 补尾、主动 write_file、提高阈值或拒绝长正例冒充通过 |
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
- 2026-10-21：原 S1 自动保存成功但分页回读失败，维持 STOP；用户选择 A，仅授权纯文档修订 Planning PR。新增可逆 JSONL/字节比较/原始证据配对与完整遍历要求；保留 SDK 0.7.28、阈值 1024、16 KiB 和所有权限边界。修订未合并前不继续实施、不进 S2、不调用付费模型或真实 K8s，不自动合并。
- 后续 S1/S2/S3 各阶段记录实际 SHA、测试命令、环境、请求次数、结果及设计偏差。**未实测项目不得预填 PASS**。

### AO 短提示词（仅本次修订 Planning PR 经审阅合并 main 后有效）

> 实施 `Vc-great/kube-triage-agent` Issue #69 的 S1→S3（必须逐 Gate 通过再继续）。先 fetch 最新 main，从独立 Worktree 读取 `AGENTS.md`、Issue #69 和 `docs/plans/issue-69-deepagents-filesystem-offloading-demo.md`。严格复用锁定 Deep Agents 0.7.28 原生 FilesystemMiddleware+StateBackend、合成 Mock+Web，不做 Summary/CLI/Host FS/Shell/Repair/真实 K8s。先从 S1 重验 F0–F3：按第 3.3 节在隔离 Graph 实现有界可逆 JSONL，原始 Reader 先校验、原生自动 Offload 后仅从 read_file 全页回执逐字节还原；原失败长正例、非零 offset、Unicode/缺页/混配/预算负测必须通过。不得把旧 PoC 或文档合并当 F3 PASS；保持 1024 阈值/16 KiB/原预算，禁止从 State 补尾。PASS 后才进入 Aegra/Web，再完成 F4–F8。保留 #41 Aegra `files` 旁路未修复记录，不把 Demo PASS 写成生产安全。需要扩大权限/外联/调用付费模型、破坏正式链路、跨 Thread 泄露或 SDK 假设不成立时 STOP。提交独立 Implementation PR（Refs #69），附逐 Gate 证据和中文报告；未经用户批准不合并、不关闭 Issue。
