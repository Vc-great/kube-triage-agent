# Issue #41 · Phase B1-R：Real Provider Contract 与 Pilot 安全门禁

> - Issue：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)，原 Phase B 验收矩阵是**唯一权威验收标准**，本文件只定义 B8 Pilot 的执行契约
> - 状态：**Proposed / Planning PR**。当前仅批准方案设计与提交本文件，不代表已授权 Provider 请求、费用或合成数据外传
> - 基线：2026-10-20，`origin/main=880f2d68cd330b6edebb9b22cab0fb1054f6b03a`；AO 开工时必须重新获取
> - 上游：[B1-R 配对评测方案](issue-41-deep-agents-real-llm-eval.md)、[B2 暂缓/B1-R Readiness 决策](issue-41-b2-scope-and-b1r-pilot-readiness.md)、[PR #55 离线 Readiness](https://github.com/Vc-great/kube-triage-agent/pull/55)（已合并）
> - 阶段授权：**仅 P0 实施（离线 Real Provider Adapter/Contract 验证）**；P1 的任何真实 Provider 请求和 P2 Formal **未授权**
> - 模型/网关：**待用户确认**。历史 `gpt-6-luna`、CPA 或 `LLM_BASE_URL` 只能作为候选，不可视为当前实际端点、价格和调用授权

## 1. 为什么需要另一个门禁

已合并 `scripts/issue41_b1r_pilot.py` 是真实 OpenAI/LangChain SDK + **强制 `httpx.MockTransport`** 的离线 Readiness：`--offline-readiness`、默认 `Limits.attempts=0`、合成模型 `b1r-offline-model`、`https://b1r.invalid/v1`，只允许离线 `--simulate-budget`；`scripts/issue41_b1r_prep.py --dry-run` 也只允许 FakeModel。它们均**没有真实 Provider 执行入口**。PR #55 最终 CI Python/Web/Compose 全绿、报告本地 534 tests / 57 项 Runner 专项，两个 Reviewer 反馈已修复；Runner 4 个冻结槽位使用 12 次**模拟** HTTP，不是 4 次真实模型测试。

既有 Readiness 每次模拟请求预留 `65536+512` **合成 Token**、固定合成费率 `0.000001` 和 `SYNTHETIC` 币种。它能证明“客户端请求预约/STOP/Mock 传输”的控制流程，但**不能证明任一真实 Provider 的 tokenizer、Hidden Reasoning、失败计费、价格、上游代理重试或账单上界**。不能直接去掉 Mock 检查、放开 socket 或让现有 `--simulate-budget` 冒充真实执行模式。

本次需要回答：真实 Provider 契约是否可验证、怎样把严格的出站与预付费风险控制实现为**默认关闭**的独立实验入口，以及在用户批准前能提供多少可信离线证据。**最小改动正式生产代码始终为零。**

## 2. 范围、不变量与授权

### P0 本次允许实现（离线）

1. 新的**独立受控 Provider Adapter / Live Pilot CLI 候选实现**：仅用于 B1-R 两个隔离 Graph `deep_diagnosis`（OFF）与 `deep_diagnosis_planning`（ON），保留 `scripts/issue41_b1r_pilot.py --offline-readiness` 原行为不变；若共享只读评测工具可复用，不允许把现有禁网入口悄悄改成可联网。
2. 以**冻结** `eval/issue41-b1r/manifest.json`、`cases.json` 和 Rubric 为输入；预选 R01/R05、replicate=1、A/B 各 1，4 Run / 2 Pair，独立 Thread，默认串行；预留 Formal 20 槽但 **P0/P1 均不得启动**。不得改 Manifest、Golden、旧失败报告或两张实验 Graph 的 Prompt/模型预算。
3. 提供可审阅的**Provider Contract Profile（仅安全配置规范）**：明确供应商、实际 HTTP 端点 allowlist、TLS/证书、API 版本/Chat Completions 兼容、模型 Request/Echo、max output、重试、Provider 用量及账单证据来源。候选 `gpt-6-luna`/CPA **不是默认值**；未知字段必须拒绝实际执行。
4. 模型传输前检查、实际客户端 HTTP 请求计数预约、单 Run/全局预算、默认零额度、熔断/终止审计；假 Transport/Mock Server 离线可测。输出私有审计和匿名人审模板，绝不记录 Key。
5. 在 P0 阶段全程禁 Provider 网络；只对冻结合成 Mock Reader 调用，测试合成结果与真实 Graph/Runner 的配对一致性。无真实 K8s、云 Langfuse/OTel、真实数据库或现有 Compose 变更。
6. AO + Codex 在最新 main 独立 Worktree 创建 Draft Implementation PR、代码测试和 Reviewer 记录；测试未跑的条目不写 PASS。

### P0 不允许实现或执行

- **任何真实模型 HTTP 请求**，包括所谓“便宜的连通性/价格探针”、自动重试、后台上传、Langfuse/其它 Trace。
- 真实 Kubernetes Reader/Repair、Namespace/RBAC 放宽、Shell/Host FS/Subagents、正式 `agent`/HITL/Memory/Checkpoint/旧 Thread 迁移。
- 不修改现有 `--offline-readiness` 和 `--dry-run` 的零出站保证；不将离线合成 Token/单价宣称真实保证。
- 不启动 B2-A/B2-B、B3 Summarization 或 P2 Formal；不关闭 Issue #41。

## 3. 设计方案与取舍

| 方案 | 优点 | 主要风险 | 选择 |
| --- | --- | --- | --- |
| **独立 Live Adapter + 客户端 HTTP Pre-send Budget Gate + 外部批准/隔离环境** | 复用现有两 Graph / SDK 和数据；可独立禁用、可审计 | 真实费用与代理上游重试不能只由 HTTP 拦截证明 | **推荐：先离线开发，真实请求需要再次 GO** |
| 直接将现有 MockTransport 换为 HTTPTransport | 代码少 | 破坏经验证的禁网契约；价格/账单与审计没有可信来源 | 禁止 |
| 把 Provider 默认注入 Aegra/Web 或正式 Graph | 易复用用户环境 | 不受控自动调用、旧线程污染、稳定系统/秘密风险 | 禁止 |
| 为 4 次 Pilot 自建全新代理/数据库/账单平台 | 可尝试中心化限额 | 复杂度显著超出单用户 Demo，仍不能保证第三方计费 | 不采用 |

### 3.1 执行组件

~~~text
仅在独立 CLI 且 P1 已批准时允许：
冻结 Manifest -> 4 Pilot Slot Scheduler（串行，0 隐式补跑）
   -> 两个既有 Deep Diagnosis Graph（A/B，参数不变）
     -> 4 原生 Reader 的进程内 Synthetic Mock（仅冻结数据）
     -> Live Model Adapter（Chat Completions，默认不装载）
         -> Pre-send Admit / Budget Ledger（每次 HTTP 实际尝试前）
         -> 固定 HTTPS 域名/路径 allowlist + TLS + 无 redirect
         -> 明确批准的 Provider / Gateway
         <- 原始响应模型回显、Usage、状态和请求 ID
     -> 原始回复安全检查 + Reader Tool ID/UID 证据校验
   -> 仅合成轨迹私有审计（0700/0600）+ 匿名盲审导出
~~~

P0 为这条链路使用 `MockTransport` / 受控本地 Fake Server 验证；任何真实 Client Transport **在 P0 必须不可达/抛错**。P1 获明确授权后才可使用受限的真实 Transport。正式 `server/src/kube_triage/llm.py` 中 `chat_model()` 的 `timeout=30`/`max_retries=1` 只是当前生产配置，P1 必须独立冻结其传输策略，不从 `TRIAGE_ENV=development` 继承 `EVAL_LUNA_RESPONSES_HIGH` / Responses High；两臂必须保持同一 Provider / 协议 / 客户端配置。

### 3.2 Provider Contract 必须先被证明

P1 前对候选 Provider 完成静态合约与独立批准。至少包括：

| Contract 属性 | 强制要求与 STOP |
| --- | --- |
| Provider 身份、模型与协议 | 确认**实际**供应商/网关、模型 Request ID、回显 Model ID、`/chat/completions` 路由和兼容功能。候选 CPA 或 `gpt-6-luna` 未经核验不可默认。若服务只支持 Responses/Reasoning 特定参数 → STOP，需单独设计，不自动切换 |
| API 地址与 TLS | 独立进程环境、单一用户批准的 HTTPS 主机名、固定端口/路径、证书验证，禁止明文远端/URL userinfo/query secret、跳转、未批准 DNS/代理出口与隐式第二端点。可显式配置已批准代理，必须纳入出口与重试模型 |
| SDK 与 HTTP | 以**仓库冻结安装版本**为准核查 OpenAI/LangChain 的 Transport、隐藏 retry、timeout、redirect、stream/Responses API、并行、缓存、tools 参数。`max_retries=0` 为简化计费的优先候选，需单独验证；如保留一次重试，每次 HTTP 仍分别预约，不得悄悄补跑 |
| Tool Calling | 真实模型返回标准 Tool Call Name/ID/Args，精确匹配四 Reader 和 B 臂 `write_todos`，外部工具执行仍为冻结 Mock；Model raw content + Tool Calls 混合必须检查。模型乱报或无法绑定 → STOP 并记录失败，不更改 Graph 冒充 PASS |
| Usage 与价格 | 至少确认 `prompt_tokens/completion_tokens/total_tokens` 及 reasoning/cache 字段语义、缺失/失败响应处理、实际币种、模型售价/代理加价及价格来源的日期。缺失统计是 UNKNOWN，不是 0；Provider 报告与账单可能不一致 |
| 数据最小化 | 只允许 `eval/issue41-b1r` 冻结合成 Prompt、工具 Schema 与 Mock Reader 返回送往批准 Provider。禁止真实 Pod Logs、`.env`、Kubeconfig、Token、真实 User Thread、Langfuse/OTel/遥测出站 |
| 稳定性 | 一次错误/超时/未知结果立即 STOP 当前批次；无隐式重试无补跑；后续恢复需全新获批准的运行标识和剩余额度核对 |

根据 [官方 OpenAI Python SDK](https://github.com/openai/openai-python) 和 [ChatOpenAI 官方文档](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI)，`max_retries`、`timeout`、`base_url`、`use_responses_api` 等可配置。但**最新文档不等于本仓库锁定版本契约**；应通过冻结版对象构造、HTTP mock、请求录制的负测核实，不能边做 P0 边升级 SDK。对第三方兼容网关尤其不能假设隐藏字段、Usage 与官方标准一致。

### 3.3 预算保证要诚实分层（关键风险）

四个 Pilot Run 并不等于四次收费：A 组每 Run 最多 4 模型决策、B 组最多 10，4 槽理论合计 `2×4+2×10=28` 决策。若每决策最多 SDK 重试一次，**最多 56 次客户端 HTTP 发送尝试**；**56 不是批准额度或推荐额度**。`max_retries=0` 时也可能有最多 28 次。用户有权批准明显更小的总额；达上限直接 STOP，不追求跑满四 Run。

P0/P1 必须分别验证并披露以下三层：
1. **客户端可保证的上限**：同一隔离 CLI 进程/串行 Run 下，在每次真实网络发送之前，原子预约**实际 HTTP 发送尝试数**；总额度与 per-Run 额度必须均未超过，失败/429/超时/SDK retry 不退额度。禁 streaming/multi-generation/redirect/异步批量补跑。任何旁路请求都必须在 OS 网络层被隔离阻断；仅 Python monkeypatch 不等于整个进程树或外部网关的封口。
2. **Token 上限的可证性**：真实模型输入 Token 上界需由该模型的**可核对 tokenizer/服务端限制**或足够保守且可验证的入场规则建立；`request.content` 字节数、离线 `Budget.INPUT=65536`、合成 `RATE` 均不能证明真实 Token 上界。`max_completion_tokens` 是否被 Provider 接受并包含 hidden reasoning 要核对；无可信上界 → Token 预算不能判硬保证、**P1 BLOCKED**。
3. **实际费用/上游不可见行为**：单次计费的最大输入/输出、失败请求是否计费、缓存/推理附加费、Provider 或 CPA 上游重试必须有来源。客户端只能限制*发往网关的请求*，不能控制网关自行重试或独立账单。如果没有可信单价/计费上界，要求用户先提供**独立预付费额度/Provider 侧硬支出上限**，并明确可承担最大暴露额；否则不能声称真实费用硬上限，P1 维持 BLOCKED。

**不允许**以请求结束后的 Usage 累加模拟预发送成本控制；可以对可验证上界按最坏情况提前扣费，收到回复只记录实际 Usage（避免将“已预留”伪作“真实已计费”）。Provider 在失败/超时后无法返回 Usage 时不能把费用记成 0 或假定已退款。无法安全实现硬界限时，继续保留离线 Runner，不以开发任务完成而批准外联。

### 3.4 生命周期与输出

- 每槽使用独立 Thread/Run/attempt ID，顺序沿用冻结 Manifest；先对照 hash、模型协议、数据白名单、安全配置和网络策略做静态 preflight。禁止使用未获批准的“探针请求”确认模型是否可用。
- 优先沿用 PR #55 的 ``Budget.reserve / receipt / score` 规则：原始模型回复在 Graph 兜底改写前检查；禁止修改工具规则以迎合输出；拒绝错误 UID、带 `tool_calls` 的恶意正文、伪造 Todo、跨 Namespace/Reader。保存 STOP 前已取得的 ToolMessage、调用 ID 与真实执行顺序。
- 执行中遇非法模型输出、HTTP/Usage 不完整、价格契约变化、Transport 漏口、重试预算失控、任意真实 K8s/云 Trace 请求立即终止后续 Run，记录脱敏失败证据。不能以最终中文报告看起来正常替代原始回包安全检查。
- 输出私有目录新建 0700、文件 0600、无符号链接/覆盖；GitHub PR 只存安全摘要、Gate 和匿名人工评分模板，真人盲审未执行记 NOT RUN。Raw Request Body 和 Key 不得上传 PR；如保留私有 Trace，应只包含合成材料且记录泄漏面。
- Pair 数据共享 Provider/模型/配置，保留两臂预算 4/10 与工具/Prompt 差异，报告仅能声称“当前 Graph 配置比较”，不声称单变量 Planning 因果收益。

## 4. 分阶段执行与人工授权清单

> **2026-10-20 P1-A 专项决策（优先适用）**：P0 已由 [PR #57](https://github.com/Vc-great/kube-triage-agent/pull/57) 合并。用户现明确选择 **CPA + `gpt-6-luna`**，并表示 P1-A 真实**合成**契约探针不再以逐笔费用/精确请求次数为商业批准门槛。详见本次独立 [P1-A CPA 设计](issue-41-p1a-cpa-gpt6-luna-provider-contract.md)。**本节既有 P1-A 模型/费用/请求授权前置，现按该专项设计适用：允许有限的真实合成 CPA Probe，但仍必须具备唯一受信出口、受保护凭据及工程防失控熔断；不可假称硬费用上界。P1-B 四槽 Pilot、P2 Formal 和真实 Kubernetes 的独立批准条件不变。** 新增 P1-A 设计在 Planning PR 合并前不生效；原 P0 和历史状态保留。

| 阶段 | 入口与当前许可 | 工作与交付 | 下阶段 GO |
| --- | --- | --- | --- |
| **Plan（本 PR）** | 仅设计，**不含外联授权** | 纯 Markdown Planning PR / Issue #41 `Refs`，不改业务代码 | 人工审阅并合并此 PR |
| **P0：Provider Adapter Contract（离线）** | 此 Plan 合并且用户按本阶段批准 | 独立 Worktree；最小 Live 候选 Adapter、MockTransport/FakeTransport、硬预算/Transport/Usage 负测、禁网 CLI 默认；独立 Draft Implementation PR/CI/Review/报告 | 无 P0/P1，所有实际测试证据可核对；不能保证费用上界则标 BLOCKED 不外联 |
| **P1-A：Provider Contract 定稿及可能的最小实测探针** | **另行明确授权** Provider/模型/端点/请求次数/Token/费用/传输范围；如契约已可离线证明，则无需额外付费探针 | 仅在批准范围内验证 Model Echo、schema、Usage、服务端计费行为；真实请求每次都占批准额度；报告 GO/BLOCKED | 模型/计费与传输 Hard Gate 均可靠 |
| **P1-B：4 Run Real Pilot** | **另行明确批准 Pilot** 的 4 槽、全部 HTTP 尝试和费用；不由 P1-A 的探针许可推导 | R01/R05 各一次 A/B，冻结 Mock Reader + 真实 LLM；Run-by-Run 保存审计与 STOP，B8 只在确有证据时更新 | 通过后决定是否人工盲审与后续 Formal |
| **P2：Formal** | **本次未授权**，P1 通过后另外批准 | 剩余 20 Run / 10 Pair、盲审与汇总 | 后续决策；不自动启用 |

### 4.1 用户未来授权必须写清的字段（不在 GitHub 提交秘密）

1. Provider/网关与模型请求标识、实际回显要求，Chat Completions 协议与**明确的 HTTPS Host/Path**；CPA 仅作为可能选项，不能凭聊天记忆猜测；TLS/代理/出口白名单与 Provider 是否可保留合成请求。
2. 是否允许**P1-A 单请求探针**（如需要），它计入单独总 HTTP 尝试、Token 和费用预算；是否同时授权 P1-B **四槽 Pilot**，默认**不同时授权**；P2 Formal 默认禁止。
3. 单 Run/全局客户端 HTTP 尝试硬上限（含 SDK retry）、单 Run/全局最大 Token、最大真实收费暴露额与币种、可验证账单/单价来源及其是否受网关上游重试影响。
4. 仅向批准端点传送的**冻结合成 Prompt、工具 Schema、Mock Reader 文本**；禁止真实日志/用户资料/秘密及 Langfuse Cloud/OTel 等额外出口，除非另行列明。
5. 允许的测试窗口、独立环境、模拟错误/失败是否允许计费；任何限制不清楚都 STOP。

**审批未填写 ≠ 使用默认值。** 执行配置文件/CLI 中出现 `--enable-live` 或额度数字不等于用户授权；AO 必须核对聊天里批准的具体范围，Runner 必须独立满足技控。不能在本 Planning PR、P0 或 CI 中使用真实凭据调用 Provider。

## 5. P0 验收方法（映射 Issue #41 B5/B7/B8/B9）

本节只细化测试方法，不新建另一套权威 Issue Gate。

| 核对内容 | 必须有的证据；未通过就 BLOCKED |
| --- | --- |
| 原 Offline 行为不变 | 旧 `--offline-readiness` + `--dry-run` 仍零 Provider/真实 K8s；默认不传参数必须零外联 STOP，禁止通过继承 `.env` 不经批准启用 |
| Provider 模型/传输契约 | 冻结 SDK + Mock 请求断言准确 Host/Path/方法/TLS/模型参数、Tool schemas、禁 stream/redirect/多个生成、各种失败/重试路径；未知 Provider STOP |
| 请求/费用预算 | 0/1/耗尽、并行拒绝、429/500/超时/失败计费未知、SDK retry 在真实传输层之前都预约；故障后不能自动跑下个槽；模拟最坏 Token/定价测试不可冒充真实保证 |
| 安全与数据泄漏 | 阻断绕过 Host、代理、DNS、其他 telemetry、真实 Reader/Repair；仅 Mock MCP；异常 STOP 仍保留已取得合成 Reader 回执、Tool ID/UID/原始模型回复检查 |
| 输入/冻结/统计 | 原 24 槽 Manifest/4 Pilot 槽 SHA 不变；A/B 顺序与 Run 隔离；真实 Usage 未执行为 UNKNOWN、`B8=NOT RUN`，盲审为 NOT RUN |
| 工程交付 | Ruff、pytest、MockTransport 集成、适用 CI、独立 Reviewer、Draft Implementation PR；真实 Head SHA、实际命令/环境、PASS/FAIL/NOT RUN/BLOCKED/UNKNOWN、回退说明 |

**额外关注：**当前 PR #55 添加约 610 行 Runner、446 行专项测试；P0 **先复用再最小增加**，避免把四槽 Pilot 做成第二套生产 Runtime。任何依赖升级、复制整个评测 Runner、修改正式 Graph、降低 UID/ToolCall/Namespace/STOP 规则或新增 Aegra API 都应停止并重新设计。

## 6. 回退与 STOP 条件

当前默认不会加载实时 Provider Adapter，不会启动任何 B2 Graph，关闭独立 CLI 即可回退。无生产服务/Checkpoint 迁移，也不能清理用户已有数据卷/线程。所有 P0 实测只运行隔离 FakeTransport/Mock Reader。

触发立刻停止：权限未批准/不完整、真实/未批准 HTTP 发出、TLS 不验证、端点/协议不符、SDK retry 未受限、无法限定 Token/收费暴露、Provider 回显与请求模型不同、Usage/账单未知却宣称硬费控、冻结文件修改、真实 Reader/Repair/云 Trace 意外出站、原始 Tool Message/UID ID 被丢失、预算超额、正式 Graph/HITL/Memory 受影响。未运行的真实 Kubernetes/Provider/人审保持 `NOT RUN`，失败保持 `FAIL/BLOCKED`，不要把旧 A08=FAIL/B06=FAIL 改掉。

## 7. AO 交接（仅 Plan 合并后有效）

- 仓库 `Vc-great/kube-triage-agent` / Issue `#41`。
- 本次合并规划：`docs/plans/issue-41-b1r-real-provider-contract-pilot-gate.md`；前置：`docs/plans/issue-41-deep-agents-real-llm-eval.md`、`docs/plans/issue-41-b2-scope-and-b1r-pilot-readiness.md`。
- **本轮唯一允许的 Codex 阶段：P0 Offline Provider Adapter/Contract**。从最新 main 独立 Worktree 开发、测试、独立 Reviewer、Draft PR，不自动合并、不关闭 #41。
- 真实 Provider/CPA、任何付费连通性探针、Pilot/Formal、真实 Kubernetes、云 Langfuse、B2/B3 一律不执行；收到真实请求需求先 STOP 请求用户另行授权。
- P0 完成后，网页 ChatGPT 核对 PR 和 Contract 证据，明确列出尚需用户决定的 Provider/模型/端点/费用/Token/实际 HTTP 限额及测试窗口。

## 8. 依据及历史保留

- 已合并：[PR #48 离线冻结评测](https://github.com/Vc-great/kube-triage-agent/pull/48)、[PR #53 阶段选择](https://github.com/Vc-great/kube-triage-agent/pull/53)、[PR #55 离线 Runner](https://github.com/Vc-great/kube-triage-agent/pull/55)。
- SDK 文档：[OpenAI Python SDK / retries](https://github.com/openai/openai-python)、[ChatOpenAI](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI)。以仓库实际锁定 `openai==3.29.0`、`langchain-openai==1.7.0`、`httpx==0.28.1` 行为为准；官方 main 后续更新不自动适用。
- B2-A 对 StateBackend 的阻断证据 PR #50/#52 **保持有效**；B2-B、B3 继续未实施。历史 A08=FAIL 和 Phase3B B06=FAIL **保留**。
- 规划日期：2026-10-20；此文件没有任何真实 Provider、真实计费、真实 Kubernetes 的 PASS 声明。
