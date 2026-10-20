# Issue #41 · 阶段范围收敛决策：B2 暂缓，优先准备 B1-R Real LLM Pilot

> - Issue：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)（仍 Open；原 Phase B Gate 为**唯一权威验收标准**）
> - 状态：**Proposed — 本纯文档 Planning PR，尚不是实施批准、费用授权或结果证明**
> - 规划基线：2026-10-20，`origin/main=88580a29a4ae4247648a3e59f96e73281bde36c4`
> - 关联设计：[Phase B2 安全设计](issue-41-deep-agents-phase-b2-context-offloading.md)、[B1-R Real LLM A/B 方案](issue-41-deep-agents-real-llm-eval.md)
> - 证据：[PR #50 原生 StateBackend 写后拒绝仍持久化](https://github.com/Vc-great/kube-triage-agent/pull/50)、[PR #52 Backend Compatibility Spike](https://github.com/Vc-great/kube-triage-agent/pull/52)，两者均已合并至 main
> - 本次批准：**阶段选择与纯文档规划**。未来合并此规划后，仅可安排 **B1-R Pilot Runner Readiness（纯离线/无 Provider）**；Pilot 和 Formal 的模型请求、外传和费用，仍须用户单独明确批准
> - 本文是决策与实施交接说明；**不修改 Issue #41 B3/B4/B5/B7/B8/B9 的既有通过标准**，不把 BLOCKED 改成 PASS

## 1. 为什么现在暂停 B2

本项目是单用户 Kubernetes 故障诊断 Demo，目标是可验证的 Agent 工程实践，不是多租户持久化文件服务。

现有能力（必须保留）：
- 正式 `agent` 的 Reader MCP、Repair/HITL、Incident Memory、Checkpoint、SSE、Context Window/Summary；无任何理由让 B2 改动正式 Graph。
- 独立 `deep_diagnosis`（Planning OFF）和 `deep_diagnosis_planning`（Planning ON），已使用真实 `deepagents==0.7.28` 的 `create_deep_agent` / `TodoListMiddleware`，B1 离线协议通过，真实模型的自主 Planning 效果仍 **UNKNOWN**。
- B1-R Prep（PR #48）：`eval/issue41-b1r/` 冻结 6 案 ×2 次 ×2 臂 = 24 槽位、12 Pair；`scripts/issue41_b1r_prep.py --dry-run` 使用 FakeModel + 进程内 Mock Reader，**没有 Provider 模式**，不能拿它直接做 Real LLM Pilot。

已确认的 B2 阻断（PR #50/#52，**不是 SDK 通用安全漏洞声明**）：

| 问题 | 真实证据 | 为什么不能在下一轮 B2-A 直接编码 |
| --- | --- | --- |
| 写后拒绝不回滚 | 原生 StateBackend 先通过 Pregel Send 排队，随后外层 ToolMessage error 不撤销文件；State/MemorySaver 仍保留 | 不可依赖写后错误作为事务回滚 |
| 同批聚合写超额 | 3 次写预算，4 个不同路径并行全部成功；降低到 1 文件/4 KiB 后两个并行写均提交 | 读同一旧 State 的 check-then-write + 进程内 Lock 不提供聚合原子预约 |
| 重复 Tool ID 与同 Thread 多 Run | 并行不同路径重复 ID 可以分别委托；同一已固定 Checkpoint 的并行 Run 会生成不同分支 | 必须定义跨调用、跨 Run/Worker 的原子预约或真正可靠的串行/拒绝机制 |
| 客户端 State 绕过 | `graph.invoke` 的 `files` 输入、`aupdate_state` 与 Aegra 更新线程状态端点的离线测试可不经 Backend 直接写入 `files` | 单纯包裹 `write_file` 不等于所有状态入口受控；需要服务端边界设计与授权 |

此外，SDK Harness Profile 的 `excluded_tools` 跨注册按并集处理；B2 需要独立进程。正式 Aegra HTTP/SSE、Postgres 重启、多进程 Worker、生产授权端点是否存在可利用漏洞均 **NOT RUN/UNKNOWN**，不可外推。

因此 B2-A 的 **Issue B3/B5=BLOCKED**，B2-B 和 B3 Summarization 尚未具备前置条件，B8 真实 LLM 仍 **NOT RUN**。PR #50/#52 的 CI PASS 只证明负面行为已复现及工程检查通过，不是 B2 功能 GO。

## 2. 选项、成本与推荐决策

| 选项 | 技术投入与风险 | 价值证明 | 建议 |
| --- | --- | --- | --- |
| **A. 继续完整 B2**：增加受信状态入口校验、跨 Worker/Run 串行、原子配额/Tool ID 预约、Checkpoint 写后确认 | 会深入 Aegra State/Run 生命周期；涉及并发、取消、TimeTravel、客户端 State 所有入口，回归范围大；SDK 扩展契约还待证明 | 当前未有真实模型显示文件工作区收益 | **NO-GO：现阶段暂缓** |
| **B. 缩小 B2**：例如最多一次串行 write_file，禁并行，阻断所有外部 `files` State 输入 | 工程代价较低但仍须逐入口、跨进程及恢复安全证明；若放弃原 Gate 则构成降低验收标准 | 能演示有限虚拟笔记，但未证实减少送模上下文 | **仅作为未来独立重新设计候选**；不视为现有 B3 PASS |
| **C. 保留证据、先完成 B1-R 真模型 A/B** | 复用已冻结数据、既有两个 Graph，新增有限 Runner/调用预算保障；真实 Provider 调用需独立授权 | 能直接检验 Planning 对复杂诊断质量、Replanning、额外 Token/延迟的价值 | **推荐先实施 Runner Readiness；Pilot 需另批** |

**阶段决策**：暂停 B2-A/B2-B 的新功能开发，而不是取消 Issue #41 的要求或修改历史失败。保持现有正式 Graph、实验 Graph、Issue 状态原样。未来仅在真实测试出现“长任务确实需要可验证外部化工作材料”且服务端状态保护方案可接受时，独立 Planning PR 再议 B2。

## 3. 下一项实施：B1-R Pilot Runner Readiness（默认禁止网络）

本任务继续复用 [已合并 B1-R 方案](issue-41-deep-agents-real-llm-eval.md) 和 [冻结 Prep 数据集](../../eval/issue41-b1r/README.md)。不新建第二套验收 Rubric，不重新生成 seed、修改旧 Golden、覆盖 24 个 Pair 槽位。

### 3.1 本阶段允许完成什么

1. 从最新 `origin/main` 的独立 Worktree 开始，阅读 `AGENTS.md`、Issue #41、此决策、原 B1-R 方案、两张现有 Deep Graph、`server/src/kube_triage/llm.py` 与 `scripts/issue41_b1r_prep.py`、真实模型旧评测脚本。核对 SDK/Provider 的实际重试和 Usage 契约，不猜历史端点。
2. **保持原 `--dry-run` 脚本永远 offline-only**。新增最小的独立 Pilot Runner/Provider Adapter 和纯离线测试；默认 disabled 且 fail closed。不能通过新开参数让旧 FakeModel Runner 偷偷使用 Provider。
3. 同一冻结 Manifest 下 A=`deep_diagnosis`、B=`deep_diagnosis_planning`；固定 R01/R05 各一次 × A/B 的 **4 Run Pilot 槽位**，不额外插入新计费 Run；避免同一 Thread/Checkpoint 和 Context 污染。只有用户明确批准才能正式连接 Provider。
4. Reader **始终为冻结合成 Mock**，不能连真实 K8s。R05 的旧/新 UID 冲突和日志注入须用 Graph 原始回执、最终答案和 Runner 规则共同评估；Runner 独立检出 UID 冲突**不能证明现有 Graph 自己已经拒绝相应结论**，允许测得 FAIL，不得为通过而临时修改基线提示词/Graph。
5. 实现**硬停止**的请求尝试数/模型决策数/单 Run 时间与 Token/费用预算边界、异常/超时/Retry 记账，保证越界时不会再发实际 HTTP 请求。底层 SDK 重试、Transport、Redirect、Streaming、并发都要纳入**请求尝试**的审计；如果无法可靠设置全局上限，结论只能是 **BLOCKED，不允许进入 Pilot**。未知 Token/定价不可默认为 0，成本不能只靠执行后估算控制。
6. 默认不读取用户 `.env` 或密钥，不连网络、不启动已有 Compose；若后续经许可使用 Provider，密钥通过批准的私有环境注入。测试构造仅合成数据，`Langfuse/OTel` 出站默认关闭；保留 Provider 实际 model_echo、Usage、请求数、失败原因和预算阻断证据，仅提交脱敏汇总。
7. 只实现最小人工盲审导出与自动规则评分（复用既有 Rubric/模板），预留 `human_review=NOT RUN`；最终统计要分别说明 A/B 原先 4/10 模型决策预算及工具集差异，不能把表现差异当成 Planning 的纯因果效果。
8. 配套离线 FakeTransport/FakeModel 测试、阻断外联、例外路径、预算上限 0/1、Provider 429/timeout/可识别 retry、错误模型回显、无 Usage、注入、Runner 路径/私有文件权限；Ruff/pytest/适用 CI，提交独立 Draft Implementation PR 和中文验收报告。

### 3.2 不可越过的授权闸门

**本规划即使合并，也只授权 Runner Readiness 的离线准备。** 实际 Real LLM Pilot 4 Run 需用户另行提供并明确批准：

- Provider/模型、API 协议与端点域名类别（不得暴露 API Key），TLS 与网络出站策略；
- 准确的 **HTTP 实际尝试总上限**（含 Provider/SDK 重试）、单 Run 与总 Token/费用上限及币种、可核对价格来源；
- 数据外传白名单：仅冻结的**合成** Prompt/Reader 回执发往批准的 Provider，禁止真实日志、Secret、kubeconfig；Langfuse Cloud/其它外传默认禁止；
- Pilot 4 Run 和具体测试窗口；Formal 另外 20 Run 是否获批只能在 Pilot 后另行决定，不因 Pilot GO 自动启动。

**STOP**：有未批准 Provider HTTP 请求/任何未知出站、真实 K8s 请求、Tool/Namespace 越权、日志 Prompt Injection 被提升为指令、预算不可计量或会超出、改写冻结 Manifest、变更正式 Agent、污染生产 Thread/Checkpoint/稳定服务。无法达到离线准备合同，则 PR 报告 BLOCKED，不能以“可运行”代替安全证明。

### 3.3 证据与复核重点

| 项目 | 离线准备可验证 | 必须留给后续经授权 Pilot |
| --- | --- | --- |
| Fixture SHA/24 Slot/4 Pilot Slot 配对 | 可标 PASS（需实际执行） | 不重复新增槽位 |
| Provider adapter 模式、HTTP 实际请求尝试拦截 | FakeTransport/Monkeypatch 测试 PASS 或 BLOCKED | 真实 HTTP 请求硬上限与 Usage 核验 |
| 工具白名单、Mock/实时 K8s 隔离、安全断言 | FakeModel + 合成 Mock 验证 | 真实模型的自主 Tool Calling、Replanning |
| Token/费用 | Fake Usage 解析可测试；真实 Usage UNKNOWN | Provider 返回真实 Usage，预算归因与价格核对 |
| 模型回答准确性、盲审 | 可冻结 Rubric/输出模板 | Real LLM + Mock MCP；人工盲审如未执行仍 NOT RUN |
| Issue B8 | **NOT RUN** | 需要用户批准后真实执行，才允许标实际 PASS/FAIL |

B2 的 B3/B5 等 BLOCKED 状态**不会**因 B1-R Runner 完成而解除。旧 Phase A A08=FAIL、Phase 3B B06=FAIL 均保持历史原记录。

## 4. 未来重新开启 B2 的条件

只有同时满足以下条件才推荐重新立项评审：
1. 经授权的真实模型评测发现具体问题（例如复杂诊断中累计输入长、需要多次引用 Evidence），有可重现样本与成本/质量数据，说明文件工作区的收益。
2. 有简洁、**SDK 支持**的服务端写入/入口控制方案，能覆盖批次/多 Run/跨 Worker 预约、重复 ID、客户端 `files` 注入、Checkpoint/恢复，不借助私有 Pregel Send 或写后错误冒充事务。
3. 不扩大 Reader/K8s 写权限、不改正式 `agent`、Repair/HITL/Memory 及旧 Checkpoint，并能提供完整隔离协议与可回退策略。

若条件不满足，B2-A 保持 BLOCKED，B2-B 保持 NOT RUN；可作为有证据支撑的工程取舍记录，而非强行验收。

## 5. 工作流、回退与交付

| 阶段 | 当前许可 | Gate |
| --- | --- | --- |
| **本次 Planning PR** | 仅添加阶段决策 Markdown，PR 审阅与人工合并；不跑模型、不实施代码 | 纯文档；Issue #41 保持 Open；代码测试 NOT RUN |
| **B1-R Pilot Runner Readiness** | 规划进入 main 后，AO 独立 Worktree + Codex + Reviewer；只能离线、无 Provider | 单独 Draft Implementation PR；FakeTransport/Mock 预算及安全实际验证；CI/审查；用户决定是否合并 |
| **B1-R 4 Run Pilot** | 另行明确授权模型、端点、实际 HTTP 请求数、费用、合成数据外传后 | 四槽位执行/真实 Usage/失败分布/Pair；若发现 P0/P1 或超额立即停止 |
| **B1-R Formal / B2 / B3** | 当前 **未批准** | 留待新决策，不自动启动 |

回退：不加载任何 B2 Graph，也不启用 Pilot Runner 网络模式；不动既有 Aegra/Compose，Runner 新增部分可独立停止或回滚 PR；旧离线 Runner 保持 `--dry-run` 语义不变。PR #50/#52 复现测试持续保留，不改成 xfail 或删除以美化结果。

## 6. AO 交接信息（仅本决策 PR 人工合并后可执行）

- 仓库：`Vc-great/kube-triage-agent`；Issue：`#41`
- 合并计划：`docs/plans/issue-41-b2-scope-and-b1r-pilot-readiness.md` 和原 `docs/plans/issue-41-deep-agents-real-llm-eval.md`
- **唯一授权阶段**：`B1-R Pilot Runner Readiness（离线）`
- 不启动真实 Provider/真实 K8s、B2/B3、不读 `.env`、不改冻结数据、不关闭 #41、不自动合并
- 交付：小型隔离 Runner、测试、中文验收、真实 CI、独立 Review、Draft PR；不能保证预算/网络零外联 → BLOCKED
- 后续授权由用户在 Runner 通过后决定；AO 短提示词仅需引用上述路径与边界

## 7. 决策记录

- 2026-10-20：`main=88580a2`，#50/#52 已合并且 B2 仍 BLOCKED。优先选择复用已有 B1-R 评测基础，不再为尚未证明收益的 B2 深入扩展 Aegra 状态协议。此结论仅是**投入顺序**调整；不删减 Issue #41 原验收，不代表 B2 永久取消或 Real LLM 已授权。
