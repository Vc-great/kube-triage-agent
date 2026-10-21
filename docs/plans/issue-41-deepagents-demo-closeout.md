# Issue #41 · Deep Agents 最短 Demo 交付设计

> **阶段更新（2026-10-21）**：P0 Core Demo 已通过 [PR #66](https://github.com/Vc-great/kube-triage-agent/pull/66) 合并至 main，最新主线 CI 全绿。用户现已同意进入 **P1 原生 Summarization** 的专项规划和后续单独 Implementation。P1 的现行技术范围、独立 Graph、SDK 证据与安全 STOP 以 [P1 专项设计](issue-41-p1-deepagents-native-summarization.md) 为准；本文件下方「P1 未批准」字样属于 **2026-10-21 P0 规划时的历史状态**，不可将其当作当前实施授权判断。P2 Filesystem 与 P3 仍需另行批准，Issue #41 B3/B8 历史 BLOCKED 不改变。

> - Issue：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)，原 Phase A/B Gate 仍是**唯一权威验收来源**；本设计调整优先级与分期，不将旧 FAIL/BLOCKED 改为 PASS。
> - 状态：**Proposed / Planning PR，未实施**；规划基线 2026-10-21 `origin/main=3490d7e3bd211d1c8d52592f676705c7717d9ee6`。AO 实施前重新 fetch main。
> - **本次批准的唯一实施阶段：P0 本地网页 Deep Agents Core Demo**。P1 原生 Summarization、P2 Filesystem、P3 最终收口只设计，必须后续分别批准。
> - 用户目标：单用户学习/面试 Demo，优先功能完整与可操作，暂停细枝末节 Rubric v2、B1-R Formal 20 Run、多租户或过度安全抽象。
> - 事实来源：[Phase B1 验收](../issue41-phase-b1-implementation-validation.md)、[B2 BLOCKED 事实与取舍](issue-41-b2-scope-and-b1r-pilot-readiness.md)、[原 B2 设计](issue-41-deep-agents-phase-b2-context-offloading.md)、[B1-R 原 Pilot STOP](../issue41-p1b-live-pilot-validation.md)、[离线归因](../issue41-p1b-stop-adjudication.md)。

## 1. 现状、真正缺口与目标

### 已实现（不再重新开发）

| 功能 | 仓库代码及证据 | 状态 |
| --- | --- | --- |
| Deep Agents SDK | `server/pyproject.toml` 锁定 `deepagents==0.7.28`，`deep_diagnosis.py` 使用 `create_deep_agent` 和 `StateBackend` | 已实现 |
| Reader MCP | `mcp_client.py` 四个受控只读工具、`kube-triage-demo` Namespace、参数/Tool ID/8s/16KiB 限制 | 已实现 |
| 原生 Planning | `deep_diagnosis_planning.py` 显式 `TodoListMiddleware`、`write_todos`、真实 `PlanningState.todos`；Reader/Todo 分开限额 | 已实现 |
| Aegra 协议 | `server/aegra.phase-b1.json` 注册 OFF/ON Graph；FakeModel + Mock Reader 已验证 Thread/Run/SSE/Checkpoint/取消/Last-Event-ID | 已验证测试范围 |
| Web | `Stream.tsx` 支持指定 assistantId；`planning-todos.tsx` 展示结构化 Todo；原 Timeline 可复用 | 已实现基础 UI |
| 真实 Provider | P1-A CPA/`gpt-6-luna` Chat Completions 三步协议验证成功；P1-B 首槽真实调用并按历史规则 STOP | Provider 兼容已证实，效果未完成 |
| 正式应用 | `server/aegra.json` 只注册 `agent`；该 Graph 独立承担 HITL/Repair、Incident Memory、Context Summary 等 | **必须保留，不整体迁移** |

### 真正缺失

1. `scripts/dev.py` 只提供现有 `real/mock/memory/...` Profile，不能一键启动 **真实 CPA + 合成 Mock Reader** 的双 Deep Graph 并从网页明确进入 ON/OFF。实验入口需要显式 `DEEP_DIAGNOSIS_ENABLE_PROVIDER=true`，不能在正式场景默认开启。
2. `scripts/dev.py` 目前 `TRIAGE_ENV=development` + `gpt-6-luna` 会走 `llm.py` 的 **Responses High**，与 P1-A 已验证的 **Chat Completions** 不同；现有 Mock Profile 还可能在模型为 Luna 时自动开启 `EVAL_LUNA_RESPONSES_HIGH=true`。新 Demo 必须显式关闭这一行为。
3. 根目录 `.env` 含完整 Langfuse 配置时，`scripts/dev.py` 自动将 `OTEL_TARGETS=LANGFUSE`；新合成 Demo 应默认**不外传 Trace**，即使用户曾配置 Langfuse Cloud。
4. Deep Agents 原生 Summarization 当前通过 Harness Profile 显式排除；`StateBackend` 已创建，但文件工具被 `excluded_tools` 隐藏；`subagents=[]`、`skills=None`、`memory=None`。Context 作为后续阶段，不要拖延 Core Demo。
5. B2 虚拟写文件已有 PR #50/#52 证明部分拒绝后仍进入 Pregel State、并发预算竞态、外部 `files`/`aupdate_state` 旁路。**这是已知 BLOCKED，不是待随意忽略的小 Bug。**

## 2. 本次目标与验收层次

**Core Demo（P0）**：用户在本机打开网页，选择 Deep Agents Planning Graph，新建 Thread，使用**真实 CPA `gpt-6-luna`** 自主决定是否调用 `write_todos` 和四个 Reader，Reader 返回**合成 Mock Kubernetes 数据**，通过 Aegra SSE 显示工具过程和结构化 Todo，最终用中文区分观察/推断/未知。可以切新 Thread 对比 `deep_diagnosis`（Planning OFF），并从启动器停止回退，既有正式 `agent` 行为不变。

**Context Demo（P1）**：独立实验中安全触发一次原生 Summarization，对比长历史；不要求 20 Run Formal，也不强制开发自定义摘要平台。

**Filesystem Demo（P2，可选扩展）**：只有安全入口可封闭时在网页开放 SDK 虚拟文件；否则在**进程内、单 Run、不向外部客户端开放 State 写入**的独立合成演示中展示 SDK 的读写能力，并保留 Issue B3 BLOCKED，不能伪称完整安全集成。

**最终收口（P3）**：写清启动方式、Graph 选择、演示脚本、实际环境和未完成 Gate；Core Demo 完成并不意味着原 Issue #41 所有 B3/B4/B8 已通过，是否修订 Issue 完成范围须另行审阅。

### 必守边界

- 原 `agent`、Reader 白名单/Namespace、Repair/HITL、Memory、旧 Thread/Checkpoint、历史 Golden/FAIL 不变；Deep Agents 不绑定 Kubernetes 写工具、Shell、Host FS、危险文件工具或 `task`。
- **P0 模型调用许可**限于用户此前批准的 CPA `gpt-6-luna` 和合成 Mock Reader 数据的有限 Smoke；无逐笔计费审批，但模型循环/超时有界、不跑 Formal。此前 CPA LAN HTTP 地址只对已批准目标成立，不能推导任意明文 HTTP 都获准。
- **P0 不授权真实 Kubernetes 数据发给 CPA、Langfuse 或别的远端模型/云服务**。真实 Reader + 真实 LLM 的数据外传应由用户另行批准。不能仅将 Reader 从 Mock 改成 Real 自动运行。
- 必须复用根目录 0600 私有 `.env` 读取和既有受限子进程注入；不得复制、打印、提交 Key、kubeconfig 或用户真实日志。`Langfuse` / `OTel` / `LangSmith` 默认 OFF。
- 只启动本次负责的本地进程、Mock Reader、必要 DB/Redis SSH 隧道；先验证占用和资源所有权，不能停止稳定 dev01/Compose/其它项目。

## 3. P0 主推荐：最小新增本地启动 Profile

### 选型

| 方案 | 代价与价值 | 结论 |
| --- | --- | --- |
| **在 `scripts/dev.py` 增加 `deep-demo` Profile**，复用 `aegra.phase-b1.json`、Mock MCP、现有 Web/Thread/SSE/Checkpoint | 修改集中，具备一键可见可操作入口；正式 Graph 不变 | **选择** |
| 将 OFF/ON Graph 加到生产 `server/aegra.json` 默认启用 | 更短，但原生产加载/权限/Provider 语义被改变 | 不采用 |
| 新建 Agent HTTP Server 和专用 Web | 功能重复、增加部署和状态系统 | 不采用 |
| P0 同时开放 B2 `write_file` | 已知客户端 State 和异步持久化绕过，额外架构工作量大 | 禁止 |

### 数据流

~~~text
make dev-deep-demo
  └─ scripts/dev.py 当前 Supervisor（复用进程身份和 stop/status）
      ├─ SSH 隧道 → 本项目已有开发 PostgreSQL / Redis
      ├─ 本地 Mock MCP (合成 Reader 数据、无 K8s)
      ├─ Aegra → server/aegra.phase-b1.json
      │     ├─ deep_diagnosis          [OFF, 仅四 Reader]
      │     └─ deep_diagnosis_planning [ON, 四 Reader + write_todos]
      │           └─ ChatOpenAI → 已批准 CPA / gpt-6-luna (Chat Completions)
      └─ Web → assistantId / Thread / SSE / PlanningTodos / 工具回执 / 中文结论
~~~

### 最小改动建议

1. `Makefile` 新增 `make dev-deep-demo`；`scripts/dev.py` 的 `PROFILES` 新增 `deep-demo`：`mock=True`、`memory_read/write=False`、`repair=False`、`window/summary=False`，尽量沿用 Mock Profile 的 DB/Redis SSH、Mock 服务、启动/停止/状态；保留既有 `make dev-stop` 进程所有权，不创建第二套守护器。启动前检查端口与 Graph。
2. 仅对新 Profile，设置 `AEGRA_CONFIG=aegra.phase-b1.json`、`DEEP_DIAGNOSIS_ENABLE_PROVIDER=true`、`DEEP_DIAGNOSIS_FAKE_MODEL=false`、`TRIAGE_ENV=test`、`EVAL_LUNA_RESPONSES_HIGH=false`。`LLM_MODEL` 精确 `gpt-6-luna`；`LLM_BASE_URL` 应核对为先前通过 P1-A 的目标，不将地址写进默认生产配置。验证实际请求路径为 Chat Completions，不能靠模型名推断；若切到 Responses High 则 FAIL/STOP。
3. 新 Profile 必须明确 `OTEL_TARGETS=""` 并且**不能自动运行 `read_langfuse_env` 或注入相关 Key**；环境变量外部继承只取允许字段，禁止自动把 `LANGSMITH`、未批准模型代理/端点、历史 Model High 配置带进去。`dev-status` 显示 `mode=deep-demo`、`reader=mock`、`model=real`、`repair=off`、`langfuse=off`、当前 Graph 配置，不打印私有值。
4. 复用已通过的 `server/aegra.phase-b1.json` 与两 Entry 开关，尽量**不修改** `graph.py`、正式 `aegra.json`、两个 Deep Graph 的安全边界、`mcp_client.py` 或 `eval/issue41-b1r`。现有 `aegra.phase-b1.json` 未复制生产 CORS 配置；若浏览器跨源实际出错，只补足**本地固定 Origin**，绝不能把 auth 关闭或设置宽泛 `*`。
5. Web 复用 `assistantId` 设置和 `PlanningTodos`，启动时打印带 `?assistantId=deep_diagnosis_planning` 的**不含 Token** 链接；保留 `deep_diagnosis` OFF 的选择说明。切换模式必须建立**新 Thread**，不能在同一旧 Thread 上无提示跨 Graph 复用 Reader/Todo State。必要时最小加提示/重置，避免复杂 Graph Selector 大改造。
6. Demo 提示词只能使用合成 Mock MCP 实际提供的 Pod/事件数据；用户看见清晰“Mock Reader + Real LLM”的标签，不能误认真实 Kubernetes。复杂用例验证计划创建/更新、Reader/ToolMessage ID；简单问候不强制建 Todo；失败/权限拒绝仍输出未知而非伪造健康/已修复。
7. 复用 `scripts/issue41_phase_b1_smoke.py` 思路扩充 Aegra 真实协议冒烟，不得用新的手写循环冒充运行 `create_deep_agent`。若要支持 Provider 成功场景，优先通过原有 `chat_model()`，不复制 `issue41_p1a_probe.py` 的低层 socket 逻辑到正常 Web Runtime；也不能因此让新启动模式自动进入真实 K8s。

### P0 检验方法（映射原 Issue #41 Gate，不另造权威 Gate）

| 原 Issue Gate | P0 必须交付的证据 | 不可冒充 |
| --- | --- | --- |
| A1/A3 | Aegra `/assistants` 返回两实验 Graph、真实 Thread/Run/SSE/History/Checkpoint、取消/重连，新旧 Run 隔离 | Python 单测 ≠ 浏览器 PASS |
| A2/A4、B5 | 模型可见/执行名单严格四 Reader 或四 Reader+1 Todo；越 Namespace、伪 AI/Tool、Repair/Host FS/Shell/`task` 全拒；旧正式 Graph 不变 | Prompt 约束 ≠ 执行权限 |
| B1/B2 | 合成复杂场景实际 `todos` 状态、基本 Replanning 或安全终止；简单聊天无需 Todo，失败不能标修复完成 | 模型请求 `completed` ≠ SDK 已应用 |
| B6 | 网页实际能看到 ON Todo、OFF 无 Todo、刷新/取消/切新 Thread 不混淆，Web lint/build；Langfuse OFF | CLI 返回文本 ≠ 前端 E2E |
| B9 | Ruff、pytest、相关 Web 测试/构建、CI/独立 Reviewer、真实 Head、启动命令/回退/人工未测项 | Mock 测试 ≠ 真实 CPA/集群 |
| B3/B4/B7/B8 | 此阶段保留历史状态；B3=BLOCKED、B4=NOT RUN、B7 历史 FakeModel PASS、B8 原 R05 STOP/0 Pair 保留 | P0 真实模型 Smoke **不等于** B8 成对 A/B |

先跑离线 FakeModel + Mock 的本机 Aegra Smoke，再在**本次已批准的合成数据范围**跑少量 CPA `gpt-6-luna` + Mock Reader 的网页/Run Smoke，分别记录请求数量、Usage、模型回显及失败；未能运行的真人浏览器验收标 NOT RUN。P0 发现任何真实 Reader 出站、额外云端 Trace、错误模型协议、Token 泄漏、Host FS/Shell/Repair 可用、跨 Thread 污染 → 立即 STOP，不以 Demo 之名豁免。

## 4. 后续独立阶段（本 PR 设计，不授权实施）

### P1 原生 Summarization：推荐先于 Filesystem

新建单独实验 Graph（或可验证的配置隔离）测试锁定 `deepagents==0.7.28` 的原生 `SummarizationMiddleware`，不改正式 `context.py`/`context_summary.py`，不双层压缩。只用每条 Reader ≤16KiB 的合成长历史/多 ToolMessage 测摘要触发/超时/故障及原始 `tool_call_id`、UID、Checkpoint 不变；保证 Summary 不把低信任日志/历史健康升级为可信当前状态，不改变审批/Memory。安全失败则回退不摘要/诊断未完成，标 BLOCKED；无需完整三臂质量评测。该阶段不能从 P0 自动开启，须独立验收与授权；原 Issue B4 未完成部分仍须保持真实状态。

### P2 StateBackend Virtual Notes / Context Offloading：可选、默认 BLOCKED

当前 `StateBackend` 并不表示文件功能已可安全开放。PR #50/#52 已证明校验后写拒绝不回滚、并发配额竞态、客户端 `files`/`aupdate_state` 输入绕过，Harness Profile 排除项跨 Graph 合并。**不允许**删除这些负测、放开生产 State 或在未验证情况下给 Web 加 `write_file`。可以在独立**进程内单 Run、没有外部 State 接口**的合成 SDK 示范中使用原生虚拟 `/scratch` 文件，标注“概念演示，B3 仍 BLOCKED”；若要对外提供完整 FS 服务，必须先有 SDK 支持的写前校验、并发/客户端入口封闭、Checkpoint 与工具 ID 可信证据，另行 Planning/Implementation Gate；无法证明就不做。项目不用因此引入 Redis 分布式文件锁或自建 FS 服务。

### P3 Demo 收口与交付

Core 演示：`make dev-deep-demo` → Web ON 图 → 真实模型生成 Todo → 合成 Reader 返回 → SSE Todo/工具/中文报告 → 新 Thread OFF 对比 → `make dev-stop`。P1 完成可追加长历史 Summary；P2 通过后才展示网页 FS Offload，否则在文档中记其为独立 SDK 演示/已知限制。写中文使用手册、已完成/未完成与剩余风险；**Core Demo 完成不是 Issue #41 所有 B3/B4/B8 Gate 完成**。若最终需缩小 Issue 的原完成定义，另经用户明确批准并按 GitHub 规范修订唯一验收标准，不能由 Worker 擅自改掉。

## 5. 分阶段任务、回退和 STOP

| 阶段 | 状态与实施范围 | 交付 |
| --- | --- | --- |
| **Planning（本 PR）** | 仅设计，代码/真实 Provider 未执行 | 纯文档 Planning PR（Refs #41），人工审阅/合并 |
| **P0 Core Demo** | **本次获准**：复用 Dev Supervisor 的新 profile、两实验 Graph、Mock MCP+真实 CPA、Web Todo、Aegra SSE/Checkpoint | 独立 Implementation PR、Ruff/pytest/Web、真实合成 Smoke、手册/中文 Gate、独立 Review |
| **P1 Summary** | 未批准；待 P0 验收后单独开任务 | Summary 独立 Graph 与长历史证据 |
| **P2 Virtual Notes / FS** | 未批准；旧 B2-A BLOCKED 未解除 | 可选 SDK 隔离演示或另行安全设计 |
| **P3 Core/Extended Closeout** | 未批准；待实际功能完成 | 可复现网页使用手册和最终 Gate |

**回退**：关闭 `deep-demo` 专用 supervisor，沿用既有 `make dev-stop` 的进程身份/资源所有权；`make dev` / `dev-mock` / 正式 `aegra.json` 不改。不迁移、删除旧 Thread/Checkpoint、稳定 Compose/卷，不重新执行失败 Pilot。

**安全 STOP**：未知真实 Kubernetes/Repair/Host FS/Shell/Task、任意新增未经允许外联（包括 Langfuse）、未获准模型/端点、Prompt/日志提升权限、工具越权、UID/ToolID 错配、旧 Graph/Checkpoint 破坏或启动器误清理他人资源；后续 P1/P2 新增 SDK API 与现有主线冲突需要重新设计。不因字面评分误报另起 P1-B A/B 或重写历史 STOP；真实语义越权仍必须 STOP。

## 6. AO 交接与设计记录

AO 仅在本 Planning PR **合并至 main** 后读取最新 `AGENTS.md`、Issue #41、本计划、`scripts/dev.py`、`server/aegra.phase-b1.json`、`deep_diagnosis_planning.py`、`llm.py` 和 Web Stream/Todos。新建独立 Worktree，核对最新 SHA 与测试资源权限，**只实施 P0**；不要为了未授权 P1/P2 复杂化实现。遇到不安全的 Provider/Trace/Mock 配置先拒绝而非放宽。

P0 Implementation PR 使用 `Refs #41`，提供真实 SHA、测试环境、Mock 与真实 CPA 独立结果、HTTP/Token Usage、负测和人工 Web 项、PASS/FAIL/NOT RUN/BLOCKED、独立审查与回滚。非最终阶段不自动合并、不关闭 Issue。

参考：[Deep Agents Overview](https://docs.langchain.com/oss/python/deepagents/overview) · [Harness Profiles](https://docs.langchain.com/oss/python/deepagents/profiles) · [Backends](https://docs.langchain.com/oss/python/deepagents/backends)；Profile exclusion 是 SDK 级工具暴露配置，且 SDK v0.7.28 实现与主线源码优先于未来版 API 文档。

**2026-10-21 决策**：核心路径优先，保留 `R05 raw_forbidden_claim STOP` / 0 Pair、B2-A BLOCKED、历史 A08/B06 FAIL；将 Rubric v2 及剩余 20 Run Formal 延后，而不是错误标 PASS。
