# Issue #41 · P1-B CPA / gpt-6-luna：真实 Planning OFF/ON 四槽 Pilot 设计与 Gate

> - [Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41) 的 **Phase B 验收矩阵**是唯一权威验收标准；本计划只是 B8 真实 A/B Pilot 的执行协议，不另立验收真相
> - 文档状态：**Implementing（规划 PR 已合并，进入 P1-B 实施；非真实 Pilot 已完成证明）**
> - 规划 PR：[PR #61](https://github.com/Vc-great/kube-triage-agent/pull/61)
> - 实施阶段：Issue #41 Phase B / B8 的 **P1-B 四槽真实 Planning OFF/ON Pilot**；实际 Runner、离线和真实执行证据见[验收报告](../issue41-p1b-live-pilot-validation.md)
> - 计划批准状态：**Approved：PR #61 于 2026-10-20 合并至 main `4af1f9f`**。用户已授权本文 P1-B 运行范围；仍须满足最新主线 CI、Runner 安全负测等全部 Gate，不能以计划批准代替实施验收
> - 适用版本：当前锁定的 `deepagents==0.7.28`、`aegra-cli==0.10.8` 及其锁文件依赖；实施时以最新 main 锁文件重新核对，不自行升级
> - 当前核验基线（2026-10-20）：`origin/main=c7393c9c39348d993fe34e08655e5999cd092cbe`；原规划基线 `b944c85` 的失败保留在第 2 节。实施前重新 fetch 并核对最新主线 CI，不能固定沿用此 SHA
> - 已合并基础：[B1-R 原实验设计](issue-41-deep-agents-real-llm-eval.md)、[P0/P1 安全设计](issue-41-b1r-real-provider-contract-pilot-gate.md)、[P1-A 合成 CPA 契约](issue-41-p1a-cpa-gpt6-luna-provider-contract.md)、[PR #59](https://github.com/Vc-great/kube-triage-agent/pull/59) 及[真实 P1-A 报告](../issue41-p1a-provider-contract-validation.md)
> - **当前新增用户授权（2026-10-20）**：只允许 **P1-B：冻结 R05 和 R01 × Planning ON/OFF，共 4 Run，CPA + `gpt-6-luna` 真实模型；仅合成 Kubernetes Reader 数据出站**。用户明确表示模型资源充裕，无需以逐笔模型费用阻碍本次任务
> - **不授权**：P2 Formal 剩余 20 Run、真实 Kubernetes Reader/Write、Repair/HITL、真实 Pod 日志/Secret 出站、Langfuse/其他云遥测、B2-A/B2-B、B3、修改正式 `agent` 或冻结评测集。B2-A 仍 BLOCKED，Issue #41 仍 Open
> - **CI-0 当前 PASS（仅针对上述核验基线）**：[PR #62](https://github.com/Vc-great/kube-triage-agent/pull/62) 已合并为 `main=c7393c9`，Push CI [39421300790](https://github.com/Vc-great/kube-triage-agent/actions/runs/39421300790) 的 Python/Web/Compose 均 PASS。旧主线的 7 项失败已修复，不再作为当前阻断。**最新主线 CI 全绿的前置 Gate 仍保留**；规划未合并或 Runner/出口隔离负测未通过时，不得执行真实四槽 Pilot

## 1. 背景、已实现事实与目标

**已完成**：[PR #48](https://github.com/Vc-great/kube-triage-agent/pull/48) 冻结 6 case ×2 repeat ×2 arm = 24 Slot；[PR #55](https://github.com/Vc-great/kube-triage-agent/pull/55) 实现 `scripts/issue41_b1r_pilot.py` 的 Real SDK + MockTransport 离线四槽 Runner（`--offline-readiness` 默认禁网）；[PR #57](https://github.com/Vc-great/kube-triage-agent/pull/57) P0 Provider Contract Mock；[PR #59](https://github.com/Vc-great/kube-triage-agent/pull/59) 单独 `scripts/issue41_p1a_probe.py` 实验，CPA `http://192.168.31.110:8317/v1` 在宿主机通过用户明确例外使用，L1 文本、L2 `pods_get` Tool Calling、L3 ToolMessage 续答，**3 次客户端 HTTP 均 200、回显 `gpt-6-luna`、原始 Usage 与 SDK Usage MATCH**。这是**真实 Wire Contract PASS**，不是自主诊断和 Planning 增益 PASS；P1-A 报告保留语义 UNKNOWN、人审 NOT RUN、模型账单/网关上游行为 UNKNOWN。

**现有 Graph**：`server/src/kube_triage/deep_diagnosis.py` 为 A/Planning OFF，`deep_diagnosis_planning.py` 为 B/Planning ON（冻结 `deepagents==0.7.28`），B 显式 TodoListMiddleware/`write_todos`；原生 4 Reader 为 `pods_list_in_namespace`、`pods_get`、`events_list`、`pods_log`。A 每 Run 最大 4 个 LLM 决策、B 最大 10；Reader 上限/白名单与 Todo 次数分开计；B/A 的 Prompt、工具表与决策预算**并不完全相同**。只能得出当前两种 Graph 配置对比，不能声称 Planning 单变量因果提升。

**本次目标**：在**实际自主 Tool Calling** 下跑原有 4 个冻结 Slot，回答是否能正确引用 CrashLoop 证据、拒绝 R05 旧 UID 与工具日志中的提示注入，B 是否有真实计划/调整/停止行为，以及实际 Token、延迟、Reader/Todo 次数和失败原因。用户已批准真实 CPA 发送**冻结人工合成数据**，不必为本次增设模型费用价格查证门槛。

## 2. 主线 CI-0：当前证据与历史失败

**当前核验（2026-10-20）**：重新 `git fetch origin` 后，`origin/main=c7393c9c39348d993fe34e08655e5999cd092cbe`。[独立 Bugfix PR #62](https://github.com/Vc-great/kube-triage-agent/pull/62) 已合并，主线 Push CI [39421300790](https://github.com/Vc-great/kube-triage-agent/actions/runs/39421300790) 的 Python、Web、Compose 均 PASS，故该基线的 **CI-0=PASS**。根因已确认：Profile 测试虽提供合成配置字典，`child_environments()` 仍会读取根目录 `.env` 的 Langfuse 配置，导致干净 CI 缺文件时失败，也使测试依赖开发机配置。修复仅为测试提供临时 `0600` 合成配置文件，并验证 OTEL 关闭、子进程无 Langfuse 字段；没有放宽产品安全校验、伪造凭据或跳过测试。本规划分支已同步该 main 修复。

**历史失败（保留，不代表当前状态）**：
- 原规划基线 `main=b944c85425e69c56644fab19af64a83f1ac36fdf`；
- [CI 39414301771](https://github.com/Vc-great/kube-triage-agent/actions/runs/39414301771) 的 Python：**7 failed, 669 passed, 3 skipped**；全部是新增 `server/tests/test_dev_profiles.py::test_profile_preflight[...]` 参数化 7 案。可见的直接错误路径为 `scripts/dev.py:read_langfuse_env` 试图读取可选 Langfuse 来源后抛 `LANGFUSE_SOURCE_UNAVAILABLE`；测试构造的 `host`/`VALUES` 未明显提供有效来源。**这是初步定位，不把原因推断当成已确认根因**。
- 近期 `main=cbc9e069...` [39413831830](https://github.com/Vc-great/kube-triage-agent/actions/runs/39413831830) 同样 7 failed；其他 Python 669 pass，Web/Compose PASS。新增 `.codex/config.toml` 的 `network_access=true` 只描述 Codex 会话权限，不代表测试子进程的网络出口自动安全。

**Gate CI-0（持续保留）**：修复合并进 main、最新 main Python/Web/Compose CI 全绿是**开始 P1-B 真实调用的前置条件**。上述基线已满足；实施前必须重新核对，若最新主线 CI 未完成或失败则 BLOCKED，不得沿用旧 PASS。新增 CI 问题仍须独立定位、最小修复，不把无关修复混入 Issue #41 Pilot Implementation PR；不得修改 `.env` 或伪造 Langfuse 凭据、删除断言、跳过 7 项测试。规划/离线 Runner 不能绕过 CI-0。CI-0 PASS 不代表规划已获人工合并、Runner 安全负测或真实 Pilot 已通过；若 CI FAIL 是更深层安全缺陷，STOP 报告而不是自行放行。

## 3. 精确实验集与安全边界

### 3.1 冻结顺序（不得重新洗牌/扩增）

始终通过 `eval/issue41-b1r/manifest.json` 原 `run_id`、`arm_order`、`replicate`、`pair_id` 驱动，固定以下 4 个 Slot（精确读取当前 Manifest 已确认）：

| 执行次序 | Run ID | Arm | 场景 |
| --- | --- | --- | --- |
| 1 | `R05-uid-injection-rep1-B` | Planning ON | 当前/历史 Pod UID 冲突、合成日志低信任 Prompt Injection |
| 2 | `R05-uid-injection-rep1-A` | Planning OFF | 完全同一合成输入/Reader 回执 |
| 3 | `R01-crashloop-rep1-B` | Planning ON | CrashLoop 证据链、日志与事件 |
| 4 | `R01-crashloop-rep1-A` | Planning OFF | 完全同一合成输入/Reader 回执 |

验 Manifest、`cases.json`、`rubric.json`、人审模板内容哈希，保持 `eval/issue41-b1r/README.md` 已冻结的对应 SHA-256（Manifest `fbd010f8fa61847efe05f84a98d1991b4ef238ea43cba20c82eecef79155df1f`）。**只执行一次原始 4 Slot；中途 STOP 不自动补跑、追加随机新 Slot 或执行 Formal**。若需要更换单个失败 Slot，应作为后续独立授权/新的运行标识和 Pair 完整性说明。

### 3.2 模型与网络

- CPA 目标**仅**使用 P1-A 已获用户明确授权、且实际探针成功的 `http://192.168.31.110:8317/v1/chat/completions` 数字 IP / 8317 / 路径；它是**唯一的 LAN 明文 HTTP 例外**，不能推广到其他 IP、任意 localhost、http proxy、外部明文地址或 TLS 关闭。`model=gpt-6-luna`，以真实回显严格比对；显式 `use_responses_api=False`、Chat Completions、`max_retries=0`、`trust_env=False`、禁 redirect/stream/异步多生成、禁止 implicit High/Reasoning API 切换。输出限制参照 P1-A `max_completion_tokens=1024` 的真实成功证据，任何变更先走 Mock 协议核验并记录。
- 秘密注入：复用 PR #59 **已经通过审查的受限进程内 CPA Key 注入路径**，只在用户先前批准的局部范围读取现有 `.env` 的必要字段，不输出/上传/提交密钥或环境全文，不复制文件到工作树；子进程/Graph 不继承多余环境。缺失/不可安全读取则 STOP，禁止在 GitHub/CI 中配置真实 Key。
- 网络隔离必须**独立于 Codex 沙箱**：优先复用 PR #59 的父进程预连接**唯一批准 IP/端口**、子进程 macOS `sandbox-exec '(deny network*)'` 及 `pass_fds` 继承已建立 socket、验证 getpeername / frozen httpcore 的受支持行为。P1-B 多轮可能发生 keep-alive 关闭，必须离线负测；如无法安全再连接，则**中止该 Run 并保留部分证据，不借用新权限、通配端口、全进程直连或网络 proxy 绕过**。只用全局 `.codex/config.toml network_access=true` 不视为 Pilot 的出口隔离证明。
- 使用**进程内静态 Synthetic Mock Reader**，绝不启动/调用真实 `mcp_client`、`k8s-mcp`、`kubectl` 或 Aegra 稳定服务。仅四 Reader 工具及 B 本地 `write_todos`；`repair`、`write_file`、Shell、`task`、Memory、Host FS 全部不可暴露。复用既有 `validate_call` 与 Namespace 校验、Reader 返回长度/超时/Tool ID、目标 Pod/UID 证据检查。
- 只允许冻结的合成 Prompt、工具 Schema 与 Mock Reader 回执发送 CPA；不含任何真实 Kubernetes/生产 Thread/Checkpoint、密钥或个人信息。`LANGFUSE`、`OTEL`、`LANGSMITH`、其它遥测/代理默认关闭；单独私有报告不上传原始响应到 GitHub。

### 3.3 成本不作为目标，防失控仍是工程门禁

用户不要求本阶段逐笔成本或正式单价证明；**实际成本、账单和 CPA 上游重试若不能独立验证标 UNKNOWN**，不使用 P0 合成 `SYNTHETIC` 费率冒充真实价格。

为了保证 Run 不会无限循环，固定当前 Graph 的 **2×10（B）+2×4（A）=28 个 LLM 决策**，设置 **全任务最多 28 次实际客户端 HTTP 尝试**（SDK retry=0）、**每 B Run 最多 10 / 每 A Run 最多 4 次**，每 Run 最多 6 次 Reader、Todo 按原生独立预算；**单请求超时 60 秒、单 Run 墙钟 10 分钟、全任务 30 分钟、串行无自动补跑**。本额度为**安全熔断，而非付费模型精确费用门槛**；若模型需要更多调用则明确 `budget_exhausted` / STOP 或给出有证据的部分结果，不扩容额度，不偷偷重试。

每次 HTTP 请求必须在**实际发送之前**预约并记录；包括失败、超时和连接断开。原始 Usage/SDK Usage 必须对应、模型回显严格等于 `gpt-6-luna`；Token 统计按真实 `usage.prompt_tokens`/`completion_tokens`/`total_tokens` 汇总，reasoning/cache 子项记录且不重复计数；缺失/超界为 UNKNOWN/STOP，不默认为 0。模型 Tokenizer、隐藏计费没有官方独立证明时如实标 UNKNOWN。工具调用、Run 时间、Input Token 预算要保留合理硬中断和单请求体大小保护；**不能**用 P0 合成 `Budget.INPUT=65536` 当成真实模型输入 Token 上界。不能给出可信上界时至少保证请求/响应体大小、调用次数和超时受限，明确成本无硬保证。

## 4. 最小实施方案

**方案比较**：

| 选项 | 取舍 | 结论 |
| --- | --- | --- |
| **独立 P1-B Live Runner，复用 `issue41_b1r_pilot.py` 既有 Graph/Mock/Score 与 PR #59 出口隔离** | 复用真实对照与守卫，改动集中在编排/Transport、审计和受控模型注入；需验证多轮实际连接重用 | **推荐** |
| 改旧 `--offline-readiness` 或 P0 `--offline-contract` 可联网 | 代码少，但破坏经过验证的默认禁网契约、混淆 Mock 与真实结果 | 禁止 |
| 直接用正式 Aegra/真实 MCP Run 模型 | 容易连真实资源/旧 Checkpoint，改变运行环境 | 禁止 |
| 另建完整 Agent Runtime/评测平台 | 重复实现单用户四槽用例且扩大风险 | 不采用 |

**组件级实现**：
1. 新增独立 `scripts/issue41_b1r_live_pilot.py`（建议名称，仅参考仓库风格）和少量专项单测；若能复用 `issue41_p1a_probe.py` 的安全出口/私有父子审计，则最小提取**稳定、可验证的公共函数**，不复制大段代码或改 P1-A CLI 行为。使用冻结 SDK 版本及现有 Deep Graph；**不能**把 P1-A 三步写死的合成 Prompt 当成 B1-R Live Runner。
2. P1-B 的模型适配必须调用 **已存在 OFF/ON Graph**，仅将冻结 `case`/`run_id`/`thread_id` 和 **真实 CPA ChatOpenAI 模型**注入隔离 `build_graph`；只把模型响应送入合成 `_reader_result`，不真实执行 `pods_get`。阅读实际 `server/src/kube_triage/deep_diagnosis.py`/Planning builder 的线程与工具闭包，不得以“类似 LangGraph”的手写循环冒充 Deep Agents 执行。
3. 复用原 Runner `Budget.receipt` 对原始 AIMessage + Tool Calls 同时存在时的正文检查、跨 Namespace/伪造工具、R05 UID/注入、失败前已取得的 Reader ToolMessages、`tool_call_id` 配对、真实 `write_todos` 状态、私有盲审导出；如现有 Frozen Rubric 不能覆盖某种表达，应显示 `human_review=NOT RUN` 或 FAIL/UNKNOWN，**不能为通过而更改 Golden 或提示词**。
4. A/B 用相同 `gpt-6-luna`/CPA 地址/SDK 协议/输出上限；执行顺序严格 Manifest；每 Slot 独立 Thread/进程/Checkpoint，不混入此前 P1-A 或其他实验历史；如果需要隔离两臂 SDK Profile 全局缓存，独立子进程依次执行，须证实不会误将 \`write_todos\`、Filesystem 等工具跨臂暴露。无 langfuse 与真实 Kubernetes。
5. 日志可检查每次原始 CPA HTTP 的请求 ID（脱敏/哈希）、finish_reason、模型回显、Usage、调用 ID、Reader 原始回执的合成证据摘要与开始/结束时间；输出使用独立新建 `0700` 私有目录、`0600` 文件，禁止覆盖/软链/print raw SDK error、stdout 不打印正文或完整数据。公开 PR 只放逐 Run 汇总/匿名得分/差异与限制，私有 Raw 不提交。

**SDK 兼容 STOP**：P1-A 冻结单 socket 三轮模型对话 ≠ B1-R 中可能数十轮自动工具循环。如果 `httpcore` 低层 socket 适配在更多 Tool Calls、keep-alive 关闭、Graph Checkpoint/取消或多个 Worker 上不能可靠工作，只报告具体 `BLOCKED/NOT RUN`，不放开网络/代理或用内部私有 Pregel Send 类似技巧拼绕过。建议先在冻结版 MockTransport 复现 **真实 SDK 多轮模型 + Reader + Todo 轨迹**，再获准使用真实四槽，防止额外付费盲测。

## 5. 实施阶段 / Gate（衔接原 Issue #41 B8）

| 阶段 | 实施/证据 | 进入下一步 |
| --- | --- | --- |
| **Planning PR（本 PR）** | 纯文档、Review、人工合并，不写业务代码，不发模型请求 | 规划合并方可派 AO 实施 |
| **Gate CI-0 主线修复** | 已通过独立 PR #62 修复；`main=c7393c9` 的 CI 39421300790 全绿，当前 PASS；历史 7 FAIL 保留，不改冻结评测、不可跳过测试 | 实施前重新确认最新 main CI PASS，且其他前置 Gate 均满足，才允许真实 P1-B 四槽 |
| **P1-B Live Runner 离线开发** | 最新 main 独立 Worktree、冻结数据、MockTransport/FakeResponse + OS 出口 Mock、预算与记录安全负测、复用已有 Graph | 单测/代码安全 Gate；不能以此宣称真实模型 PASS |
| **P1-B 已批准的真实四槽 Pilot** | 仅本文 4 Run；真实 CPA + 合成 Mock Reader；串行、真实 Usage、失败立即 STOP；报告 STOP/GO、Pair 完整性与安全证据 | 仅完整与有效 Pair 才能进行适当 A/B 比较 |
| **Independent Review & CI** | Reviewer 对最终实现 Head/结果文档双审，适用 Ruff/pytest/CI；Draft Implementation PR | 用户审阅决定是否合并；Issue #41 仍 Open |
| **P2 Formal 剩余 20 Run** | **未授权、不得自动执行** | 必须有独立用户明确授权与新阶段记录 |

**验收方法**（原 Issue #41 Phase B Gate 权威）：CI-0 的 `main` 测试通过；B5 原始日志注入/UID/Namespace 验证；B7 Manifest/Golden不变；B8 真实模型 + **Synthetic Mock** 配对 4 Slot、统计实际 Reader 与 Todo、模型决策数、Usage/延迟/出错/拒绝、原始证据及人工盲审状态；B9 完整 Reviewer/CI/风险记录。每项分别标 `PASS/FAIL/NOT RUN/BLOCKED/UNKNOWN`；**不能以 4 个模型 Run 都返回 200 推导 B8 自动 PASS**，更不能说 B2 已实现。

**可能的结论**：
- `GO_B1R_FORMAL_CONSIDERATION`：4/4 Run 均有可审计轨迹，2/2 Pair 可比、无 P0/P1 安全事故，人工评分如未完成明确 NOT RUN；可讨论是否批准 P2，但 **不能自行执行**。
- `NO_GO_OR_BLOCKED`：模型调用正常但语义/证据失败、UID 归因错误、注入成功、非法工具、缺失配对、重复请求、出口与成本不可控；记录失败与未完成 Pair，不重试/扩大样本来美化结论。
- 即使 B 优于 A，也明确 A/B 决策上限 `4/10` 和不同系统 Prompt/工具导致混杂，不能做 Planning 因果声称。

## 6. 回退 / STOP 条件

- **强制 STOP**：新 main CI 没有恢复 GREEN 却要跑真实四槽；实际联网到未批准地址、未经核实的明文 HTTP/代理、Key 或合成之外数据上传；`LANGFUSE/OTEL` 非授权外联；真实 Reader/Repair/Kubernetes 接触；模型发送次数、并发、Budget、Reader、UID/Tool ID/敏感数据越权；Graph 的工具表跨臂污染、原始 ToolMessage 被吞或改变其证据；冻结输入变化或需放弃旧 checkpoint；意外重试、自动进入 Formal。
- **回退**：停用独立 P1-B CLI / 不注册任何新 Graph；不改正式服务、用户数据库与 Checkpoint；如存在 CI-0 独立 Bugfix，按其 PR 单独评估回滚。P1-A/P0 原工具无行为变化，旧失败（Phase 3B B06、Phase A A08）和 B2-A BLOCKED 保留。
- **报告**：真实 Head SHA、主线 CI 修复 PR/Run、冻结 Fixture SHA、各 Run 的 Model Echo/HTTP Attempts/Usage/延迟/Reader/Todo/Tool ID/UID 统计、自动规则评分/匿名盲审、人审 NOT RUN 若未执行、任一 Fail/Stop/旧失败证据、实际网络/秘密边界与环境、Reviewer 对同一最终 Head 的判定，不能把 CI 作者声称测试作为独立 Reviewer 复测。

## 7. AO 交接（仅本 Planning PR 合并后有效）

- 仓库 `Vc-great/kube-triage-agent`，Issue `#41`；唯一批准阶段 **P1-B 4 Run Real Planning Pilot（含必要的离线 Runner 实施）**。
- 首读 `AGENTS.md`、本计划 `docs/plans/issue-41-p1b-cpa-planning-real-pilot.md`、`docs/plans/issue-41-deep-agents-real-llm-eval.md`、PR #59/`scripts/issue41_p1a_probe.py`、`scripts/issue41_b1r_pilot.py`。
- **重新核对 CI-0**：PR #62 已修复历史 7 个 `test_dev_profiles` 错误，`main=c7393c9` 的 CI 39421300790 全绿；若后续 main CI 未完成或失败，仍须等待/用独立最小 Bugfix PR 修复，不得跳过或掩盖，真实四槽不得开始。
- 真实 CPA 入口采用用户已批准的精确 `192.168.31.110:8317/v1`、`gpt-6-luna` 和既有安全的私有密钥注入；本次用户批准发送仅冻结合成用例。
- 工程硬熔断：**4 Run、28 HTTP 实际尝试、无 SDK retry、串行、60s/请求、10min/Run、30min/任务**；所有失败 STOP，无自动补跑。最小代码、Fake/Mock 负测后才真实调用。
- 独立 Worktree/Reviewer、Draft Implementation PR、中文 Gate 报告/CI。**不得自动合并、关闭 Issue #41、进入 P2 20 Run / B2/B3、实际 K8s 或任何写权限扩大**。因安全或缺失配置无法执行，提交 BLOCKED 证据，不用“资源充裕”绕过边界。

## 8. 设计记录

- 2026-10-20：基于 `main=b944c85`、冻结清单与 PR #59 真 CPA Wire 结果确定 P1-B 四槽受控实测。此设计创建时 `main` 的 Python CI **7 FAIL**，故 CI-0 前置，不伪称已修复。历史 P1-A L1/L2/L3 3 次成功不是 P1-B 结果。
- 2026-10-20 CI 修复更新：PR #62 合并至 `main=c7393c9`，主线 CI 39421300790 的 Python/Web/Compose 全 PASS；本规划分支同步 main 并更新当前证据，保留上述历史失败。持续保留最新主线 CI 与其他安全 Gate，不把本次 CI 修复当作 P1-B 执行证明。
