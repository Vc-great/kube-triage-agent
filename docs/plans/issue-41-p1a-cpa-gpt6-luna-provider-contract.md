# Issue #41 · P1-A：CPA 网关 + gpt-6-luna 真实 Provider Contract 核验

> - Issue：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)（**唯一权威 Phase B Gate**）；本文件只细化 P1-A 执行方案，不新建一套 B8 验收标准。
> - 状态：**Proposed / Planning PR**，规划基线 2026-10-20 `origin/main=b8cb973cadb74ef4fa7def3cf656a1d811002d67`。
> - 前置：[PR #56 P0/P1 设计](issue-41-b1r-real-provider-contract-pilot-gate.md) 和 [PR #57 P0 Provider Adapter](https://github.com/Vc-great/kube-triage-agent/pull/57) 已合并；[B1-R A/B 方案](issue-41-deep-agents-real-llm-eval.md) 与[阶段取舍](issue-41-b2-scope-and-b1r-pilot-readiness.md)保持有效。
> - **用户本轮决策**（2026-10-20）：指定 **CPA 网关 / 请求模型 `gpt-6-luna`**，P1-A 可为**合成契约探针**使用真实模型；资金和请求次数不是业务验收门槛，希望快速验证。**并非授权**真实 Kubernetes、真实日志/Secret 出站、P1-B 4 Run Pilot、P2 Formal、B2/B3、绕过网络/工具安全。
> - 实际 CPA `base_url`、Key、端点是否支持 Chat Completions、回显模型、Usage/内部重试仍 **UNKNOWN**；不得从历史对话中猜 URL、凭据或价格。
> - 规划 PR 合并至 main 后，AO 才可实施 P1-A；本 PR 不执行任何模型调用、网络探针或业务代码改动。

## 1. 现状与本次要解决的问题

最新 `main` 的 `scripts/issue41_b1r_pilot.py` 是离线 Readiness，`scripts/issue41_provider_contract.py` 是 P0 合成 Contract：后者的 `ProviderProfile.live_gate()` 固定返回 BLOCKED，仅接受 `httpx.MockTransport`，模型固定合成 `contract-request-model`，没有凭据或真实 Transport 工厂。PR #57 的 585 pytest、CI 和 AO Review 只证明离线兼容与隔离。**P1-A 不能直接把 P0 中的 Mock 检查删除、把 `.invalid` 地址替换成真实地址就发送请求。**

目标是用尽量少的代码、实际少量真实请求回答：
1. CPA 当前提供的 `gpt-6-luna` 能否通过仓库锁定的 OpenAI SDK / `ChatOpenAI` **Chat Completions** API 成功生成文本？
2. 标准 `tools` / `tool_calls` / `tool_call_id` / `ToolMessage` 多轮续答是否遵循 LangGraph 现有契约？能否在真实回包中看到合法模型回显、状态、`finish_reason` 和 `usage`？
3. 当前 CPA 是否重写模型名、Tool Call ID、参数、Usage 或工具响应；是否有代理级隐式重试、失败后重复请求、可观测数据缺口？
4. 若结果不兼容，明确卡在哪一层，并提供脱敏、可复现的 STOP/NO-GO，而不是再继续堆叠 P0 代码。

**不评估 Planning ON/OFF 的真实诊断质量**：那是需要独立批准的 P1-B 4 Run Pilot（R01/R05 × 两臂）。P1-A 仅对 Provider Wire Contract 做实证，不得提前跑完整 A/B。

## 2. 授权解释与最小安全边界

本计划是对[上游 P0/P1 设计 `4](issue-41-b1r-real-provider-contract-pilot-gate.md)在**仅 P1-A**范围内的具体化及有限例外：

- **费用/精确计费豁免**：用户明确表示资源充裕、不要求为 P1-A 再设置逐笔费用与精确请求次数的审批门槛。真实定价、隐藏 reasoning token、上游实际计费与失败计费**仍记录为 UNKNOWN（若无法核验）**，不再仅因缺乏价格表阻止本次有限合成探针；不得在报告中伪称硬费用上界。
- **工程熔断不豁免**：为了防模型/SDK 无限循环，固定 **单个 P1-A 任务最多 24 次客户端实际 HTTP 发送尝试、总墙钟 10 分钟、单次 45 秒、`max_retries=0`、串行无自动补跑**。它们是异常保护，不是成本授权上限；通常仅需 3–8 次请求。超出则 STOP，不能悄悄提高或开启 P1-B。每次发出前记录与预约；SDK/代理上游隐藏重试无法被客户端声称“全局无重试”，需如实标 UNKNOWN。
- **合成数据范围**：允许 P1-A 向**用户现有 CPA** 仅传输人工构造、不包含真实 Pod/历史 Thread 的 Probe Prompt、四个只读 Reader 的工具 Schema（如有需要）、小段合成 ToolMessage（固定 `kube-triage-demo`、假 Pod 名/UID）以及协议必需元数据。严禁发真实日志、Secret、个人数据、kubeconfig、真实历史会话；`Langfuse/OTel/LangSmith` 出站默认关闭。
- **隔离**：不启动正式 Aegra/Web/Repair/真实 MCP；不读取/打印/提交 `.env`、Key 或代理配置凭据。使用**用户提供的私有进程环境/密钥注入**而不是从仓库配置文件提取；不可提供时判 `BLOCKED_CONFIG`，不得私下搜索 Secret。
- **网络**：只连**实际确认的 CPA 地址**。远端必须 HTTPS + TLS 验证；若现有 CPA 是本机本地代理，可**仅**允许精确 `127.0.0.1` / `::1` loopback HTTP，并校验端口/路径，禁止 `0.0.0.0`、`localhost` DNS 假冒、用户信息 URL、跳转或额外 host；其上游网络和账单不可见须披露。是否通过单独 HTTP 代理路由必须从用户明确提供的无秘密出口配置核实，不能无条件继承 `HTTP_PROXY` / `HTTPS_PROXY` 或关闭证书验证。
- **旧边界不变**：正式 `agent`、Reader MCP 四工具白名单、`kube-triage-demo`、UID 与 Tool Call ID 校验、HITL/Repair、Memory、旧 Checkpoint、冻结评测 Manifest 不改。P1-B 和 P2 未批准；Issue #41 的 B8 仍为 NOT RUN 直到真正执行规定配对试验。

**若实际 CPA 目标端点不明、TLS/loopback 边界无法成立、凭据未安全注入或真实出口不能限制到批准的 CPA**：可交付静态核验报告，但不得发送网络请求，记 BLOCKED 并提出需要用户补充的非敏感配置项。

## 3. 推荐方案与取舍

| 方案 | 价值 | 风险/成本 | 决策 |
| --- | --- | --- | --- |
| **独立 P1-A Live Probe CLI + 复用 P0 Contract 的 HTTP/Message Guard** | 真实验证 CPA 的 Chat Completions 与 Tool Calling；保留 P0 零出站契约 | 需新建经过审查的受限真实 Transport 与秘密注入；上游行为不可完全观测 | **推荐** |
| 放宽 `OfflineAdapter.guarded_transport`，直接用现有离线 CLI 联网 | 修改少 | 会使已验证的 P0 默认禁网失效，也可能把合成预算当真实账单 | 禁止 |
| 通过生产 Graph 直接测 CPA | 省少量适配代码 | 真实 MCP/稳定环境/旧 Thread 混入，审计困难 | 禁止 |
| 使用未验证的 Responses High 自动回退 | 可能兼容某些代理 | 破坏本次 Chat Completions A/B 可比性、请求协议/工具行为不同 | 不自动启用；仅记录单独后续设计需求 |

参考：[ChatOpenAI 官方参考](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI) 提醒自定义端点下应**显式**设置 `use_responses_api=False`，不要依赖模型名推断；[OpenAI Python SDK](https://github.com/openai/openai-python) 说明 `max_retries=0` 可禁用其客户端自动重试。**两份官方最新文档不等于仓库锁定版本实测**；以 `openai==3.29.0`、`langchain-openai==1.7.0`、`httpx==0.28.1` 的本地源码、MockTransport 和真实探针为准。

### 3.1 适配与执行流程

~~~text
[独立 P1-A CLI]（绝不复用 P0 --offline-contract 的联网入口）
  ├─ 静态 Preflight：确认 main / SDK lock / 已批准 CPA URL 类别 / 私有凭据存在
  ├─ 默认 OFF：显式选择 P1-A LIVE 模式 + 任务批准范围 + 非敏感 endpoint allowlist
  ├─ 请求前 Guard：model=gpt-6-luna / Chat Completions / Tool allowlist /
  │                   TLS 或 exact loopback / 24 attempts & 10min circuit breaker
  ├─ 最小 httpx AsyncHTTPTransport（定向出口、无 redirect、trust_env=False）
  ├─ 锁定 ChatOpenAI / OpenAI SDK（max_retries=0、streaming=False、
  │    use_responses_api=False、max_completion_tokens 按 wire 实证配置）
  ├─ CPA 实际 HTTP 回包（先保存脱敏原始包的结构/模型/Usage，
  │    再检查 SDK AIMessage 转换）
  └─ Probe 报告：Client attempts / HTTP status / request_id / echo model /
     ToolCall↔ToolMessage / reasoning/cache Usage / latency / GO or BLOCKED
~~~

仍复用 `scripts/issue41_b1r_pilot.py` 的消息安全校验思路和 `ProviderProfile` 约束；**不要**复制 610 行 Runner、也不要把真实 Provider Transport 注入 P0 的 `OfflineAdapter`。P1-A 是单独的少量合成协议请求，不预加载 R01/R05 的完整冻结测试样本，不运行 4 槽 A/B。

### 3.2 逐项探针（先成功路径、再边界）

| 探针 | 实际行为与目的 | 验收证据 |
| --- | --- | --- |
| L0 静态与禁网回归 | 检查冻结版本、P0 三个离线入口与默认 P1-A `--help` / 无权限行为；专用临时目录 0700/0600 | P0 零真实请求；未获 live 条件则 0 请求 STOP |
| L1 文本 Chat Completions | 一次纯合成中文请求，锁定 `gpt-6-luna` / non-stream / 最大输出 Token；不加不受支持参数 | 实际 HTTP 200/失败码、`response.id`、`model`、`finish_reason`、`usage`、SDK `AIMessage` 内容；缺失标 UNKNOWN |
| L2 标准 Tool Calling | 绑定**合成 Reader 工具 Schema**，明确要求模型请求调用 `pods_get`（`namespace=kube-triage-demo` / 假 Pod），仅捕获参数，不调用 K8s | `tool_calls` 数组、唯一非空 Tool ID、合法工具名/Namespace/参数；不经许可工具则 STOP |
| L3 ToolMessage 续答 | 将固定假 `pods_get` 证据回执按上轮 Tool ID 送回，同一合成对话要求中文有限结论 | 调用 ID 配对、Pod UID/Namespace 不被换、未伪造“已核验健康/已修复”、SDK 返回最终答案 |
| L4 能力边界 | 仅在 L1–L3 合约成功后，可追加一次纯合成 R05 风格旧/新 UID 矛盾或 Reader 403/日志注入负测，不发真实日志 | 不要求 Agent“必须判断具体根因”；原始证据、拒绝指令与有限结论保留；失败标 FAIL |
| L5 故障模拟（无付费请求） | 通过本地 MockTransport 测试 429/500/断连/超时/Usage 缺失/模型回显不同/HTTP redirect/额外工具/越界路径 | 实际请求不会泄漏至第二目的地、STOP 锁存、审计正确、不会自动继续执行批次 |

**不对外制造真实 429 或主动破坏 CPA 环境**；错误分支全部离线模拟。不要用固定完整答案断言模型自然语言质量；P1-A 验证的是协议能力，语义质量交给 P1-B。

### 3.3 真实 API 差异处理

- 请求 `model=gpt-6-luna`；记录原始响应 `model`、`id`、HTTP status、`x-request-id`（有则记录**脱敏**）、`usage.prompt_tokens/completion_tokens/total_tokens`、`prompt_tokens_details.cached_tokens`、`completion_tokens_details.reasoning_tokens`、`finish_reason`。不因 SDK 提供 `usage_metadata` 就忽略原始回包；两套对比，缺失保持 UNKNOWN。
- `ChatOpenAI` / CPA 可能不支持 `max_completion_tokens` 或支持 `max_tokens`、模型最终回答可能因 reasoning 耗尽而为空。**先记录实际 400/422 错误结构与所用参数**；仅在预先列入设计的兼容变体中**人工审阅请求差异后**再发一个受控探针，不在 SDK 内静默改写或自动切换 Responses。推荐首先尝试输出上限 1024/2048（以模型支持与真实回包确认）；不设置危险高 reasoning effort。
- CPA 回显模型名可能是路由后的别名。`model_echo != gpt-6-luna` 时先标 `MISMATCH`，列出代理映射证据并 STOP，不能私自修改预期模型名或把别名视为同一个真实模型；不能验证时 B1-R 与 gpt-6-luna 结论不能成立。
- 提供**两层计数**：客户端可实际观察的 HTTP 尝试/模型决策，与 CPA 隐形上游调用（通常 UNKNOWN）。真实 Token/价格不作为 P1-A 的审批门槛，但为了未来 A/B 可比性，实际 Usage 必须记录，缺失如实标记。
- Adapter 绝不声称能直接观察 CPA 上游模型版本、隐藏推理、内部重试或真实账单；P1-A 成功只表示约定接口在这一组有限合成探针下可用。

## 4. 工作阶段与可复核证据

| 阶段 | 执行权限 | 交付 |
| --- | --- | --- |
| **Planning PR（本轮）** | 仅新增文档 / 更新上游设计链接；不运行实际 CPA | 独立 Draft Planning PR、分支与 Head SHA、审核后人工合并 |
| **P1-A 1：离线适配 + Preflight** | 合并设计后 AO 实施。允许改测试脚本/离线负测，不读 `.env` | 新 CLI 最小受限 live 通道、旧 P0 回归、真实请求前 0 次负测、独立执行记录 |
| **P1-A 2：真实 CPA 合成探针** | **本次用户已批准 P1-A** 的 CPA/`gpt-6-luna` 合成探针，前提是非敏感 URL/私有环境可确认、准确唯一出口、无真实数据；24 次防失控熔断 | L1/L2/L3 基础真实请求、可选 L4、安全审计、原始回包结构和 SDK 映射、中文 Gate 报告 |
| **独立 Review/CI** | 对同一 Head 做测试、静态审查、必要修复；不继续扩大范围 | Draft Implementation PR、最终 Ruff/pytest/CI、PASS/FAIL/BLOCKED/NOT RUN、GO/NO-GO 建议；不自动合并 |
| **P1-B / Formal** | **未批准** | 必须经用户审阅 P1-A 结果后才单独启动四槽 A/B 与剩余 20 Run |

### 4.1 检查方法（只映射 Issue #41 B5/B7/B8/B9；不是新验收真相）

- **Scope / Exit**：新 Worktree 起始实时 SHA、真实锁定 SDK、仅合成探针；URL 匹配目标、端点/凭据注入、端口与 TLS/loopback 验证；OS 网络出口策略尽可能限制目的地，若不能保证安全出口则 STOP，不用 Python monkeypatch 充当完整 OS 隔离。
- **协议**：真实 Chat Completion 回执支持标准 `tool_calls`，Tool ID 与 ToolMessage 对应，模型回显/finish_reason/Usage 明示；模型能力局限可标 PARTIAL/BLOCKED，不能为通过而修改冻结规则/生产 Graph。
- **安全**：未知工具、跨 Namespace、Prompt Injection、真实 Pod/Secret/Trace、HTTP redirect、另一地址、HTTP 明文远端、无 TLS/违规代理均拒绝；合法的合成 Tool Message 不等于真实 Reader Kubernetes 结果。
- **稳定/审计**：固定 24 HTTP 发送尝试熔断/10min，`max_retries=0`；429/5xx/超时/接口不兼容即保留错误并 STOP，不悄悄补跑。只记录 URI 的非敏感 host、模型、HTTP 状态/Usage 类型/脱敏 request ID；敏感 Key/完整异常栈/Authorization 不入 GitHub。
- **回归**：原三个离线 CLI、Runner 冻结 Manifest 的 24/4 样本与 FakeModel 不变；Ruff、pytest、可用 CI、独立 Reviewer。P1-A 少量真实模型 Smoke **不自动证明** P1-B 的 B8 PASS。
- **未测明示**：真实 Kubernetes、真正 R01/R05 4 Run Planning A/B、真实 CPA 账单/上游透明路由、Langfuse、真人盲审全部 NOT RUN/UNKNOWN，B2-A 仍 BLOCKED、B2-B/B3 不实施。

## 5. STOP、回退与 AO 交接

**STOP**：安全环境配置缺失、未经批准的 CPA 地址/代理出口、密钥被记录或实际外传敏感数据、不可验证 TLS、安全白名单越权、旧 P0 禁网回归、错误 Endpoint/Model Echo、Tool Call ID 不配对、异常无限请求、需要生产 Aegra/真实 Kubernetes/新权限、SDK 强制切 Responses、需要修改冻结样本或正式 Agent；无法满足就报告 BLOCKED 而不是“降级放开”。

回退：单独退出 P1-A CLI / 不加载 live Adapter；保留 P0 默认禁网、不更改正式服务、数据库和旧 Thread/Checkpoint。禁止删除稳定 Compose 或既有文件；只清理当前任务自建的临时测试资源。所有私有原始轨迹仅留本机，不经 PR 或云 Trace 公开。

AO 交接约束：
- 仓库 `Vc-great/kube-triage-agent` / Issue `#41`；
- **待本 Planning PR 合并到 main**，阅读 `AGENTS.md`、本方案 `docs/plans/issue-41-p1a-cpa-gpt6-luna-provider-contract.md`、已合并 P0 方案和 PR #57。
- 只执行 **P1-A CPA / gpt-6-luna Wire Contract**；可在本次授权下发必要的**纯合成**真实 CPA 请求，不额外要求用户填写费用；本轮工程熔断 24 HTTP 尝试/10min/串行/无 SDK Retry，不能跨阶段使用。
- Key 从私有安全环境注入，不读 `.env`；URL/凭据不可安全获取时 STOP 并说明**缺少哪项**（不输出值），不要把已授权理解为必须想办法绕过安全检查。
- 独立 Worktree、最小改动、离线负测 → 合成真实探针 → 报告/Reviewer/CI → Draft PR；不合并不关闭 #41。
- P1-B A/B 和 Formal、真实 Kubernetes、B2/B3 不在任务范围。

## 6. 决策记录

- 2026-10-20：用户明确选 CPA + `gpt-6-luna`，允许 P1-A 以真实 CPA 请求核对接口，放宽 P1-A 的计费/审批阻碍；**保留防失控、出站白名单、敏感数据与阶段边界**。历史 P0 的 `live_gate=BLOCKED` 是正确的实现隔离，P1-A 不修改其语义，也不将离线 585 tests 冒充真实验证。
