# Issue #28 Gate B：离线验收

执行日期：2026-10-15（Asia/Shanghai）。`git fetch origin main` 后 `origin/main=756c4311e21a308fd8e56178b990ffa644665f09`，与提示词基线相同，无额外远端差异。PR #29 已合并，merge SHA 同上；Issue #28 Open。PR #29 正式 Review 列表 `[]`，独立记 `GATE_A_REVIEW=NOT RUN`，不作为本轮阻断。Gate A `context.py`、`graph.py`、配置、23 个测试和验收文档均在 main；未发现影响安全实施的可复现 P0/P1，故本轮 `B00=PASS`。旧一次 B00 BLOCKED 记录不修改。

Worktree：`/Users/vc/.codex/worktrees/issue28-gateb-summary/kube-triage-agent`；分支 `codex/issue28-gateb-summary`，从上述 SHA 创建。开始时新 Worktree 无未提交文件；主工作树的 `apps/web/AGENTS.md`、`apps/web/CLAUDE.md` 两个未跟踪文件未触碰。未安装依赖、未启动 Compose、未发 Provider 请求、未访问真实 Kubernetes。

## 证据等级与矩阵

L0=纯函数/配置/静态检查；L1=FakeModel 与 Mock/工具 spy；L2=MemorySaver `ainvoke()`/Checkpoint；L3=真实模型加 Mock MCP（NOT RUN）；Real K8s=NOT RUN。PASS 只指表内层级。

| ID | 状态 | 证据与边界 |
| --- | --- | --- |
| B00 | PASS | 最新 main 包含已合并 Gate A；PR #29 Review=0 单列 NOT RUN。 |
| B01 | PASS | 默认关闭或短 Thread，原临时送模输入逐消息一致，0 摘要请求、0 Summary State 写入；L1。配置依赖非法值 fail closed；L0。 |
| B02 | PASS | 10/20/30 轮完整历史，估算不超过 6500，当前轮对象不变；30 轮触发有界源回退；L0/L1。 |
| B03 | PASS | 新 Human 和 MemorySaver 第二次 `ainvoke()` 复用缓存；指纹改变重算，同轮失败仅一次摘要尝试；L1/L2。 |
| B04 | PASS | 当前轮并发成功/失败 Tool ID 原样保留，`_counts` 与 `_has_tool_evidence` 只看原 State；L1。既有 4 决策/6 工具测试继续通过。 |
| B05 | PASS | 合成历史 Healthy/旧 UID 与当前 CrashLoop/新 UID 消息仍完整；无当前工具证据时不能证明健康；L1。真实语义判断 NOT RUN。 |
| B06 | PASS | 坏 JSON、未知字段、伪 System、`/repair-demo`、审批/Scale、虚拟秘密哨兵拒绝或回退，错误正文不入审计；L0/L1。真实模型抗注入 NOT RUN。 |
| B07 | PASS | `/repair-demo` 绕过摘要；既有 `test_phase3b.py` 的 Reject/Approve/Resume 使用 Mock/MemorySaver，真实 K8s 写 0；L1/L2。历史 #15 B06 FAIL 未改。 |
| B08 | PASS | Timeout、429、非法摘要、源超限、Gate A `rejected` 安全回退或明确停止；不会发送超预算全量历史；L1。 |
| B09 | PASS | MemorySaver 保留所有原始消息，摘要独立 State 字段；第二轮 `ainvoke()` 可读缓存；L2。Aegra SSE/UI 真实验收 NOT RUN。 |
| B10 | PASS | 固定合成 10/20/30 轮对照可复现；仅验证哨兵字符串在临时输入的保留，不代表真实模型质量；L1。真实 Token/成本收益 NOT RUN。 |
| B11 | NOT RUN | 未获独立 Provider 请求授权；真实模型 + Mock MCP、真实 usage、人工事实评分均未执行。 |
| B12 | PASS | Ruff、全量 pytest、Manifest、两套 Compose `config --quiet`、`git diff --check` 本地通过；Draft PR 与远端 CI 状态见下方，独立 Review 待完成。 |

## 固定合成对照

执行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=server/src /Users/vc/code/kube-triage-agent/server/.venv/bin/python scripts/eval_issue28_gateb.py`。固定 `CONTEXT_ESTIMATED_TOTAL_BUDGET=6500`、四个 Reader Schema、每轮 Human/AI Tool Call/ToolMessage/AI、合成 `SYNTHETIC_PENDING_UID_OLD` 哨兵。`estimated_input` 使用 Gate A 估算单位，已含 2048 输出预留；不是 Provider Token。`cache_hits` 是新 Human 后第二次调用的次数。

| 轮数 | Gate A estimated_input / omitted_rounds | Gate B estimated_input / omitted_rounds | summary_calls / cache_hits / output_chars | 固定哨兵保留 A→B | fail_reason |
| --- | --- | --- | --- | --- | --- |
| 10 | 6255 / 6 | 4757 / 9 | 1 / 1 / 179 | 0/1 → 1/1 | 无 |
| 20 | 6262 / 16 | 4759 / 19 | 1 / 1 / 179 | 0/1 → 1/1 | 无 |
| 30 | 6262 / 26 | 6262 / 26 | 0 / 0 / 0 | 0/1 → 0/1 | `source_over_budget`；回退 Gate A |

摘要成功分母 2/3，安全回退分母 1/3。哨兵保留由固定 FakeSummarizer 根据源中哨兵输出，属于人为确定性 L1 检查；未评分任何真实诊断事实。`actual_input_tokens`、`summary_input_tokens`、`summary_output_tokens`、费用为 **UNKNOWN**；Provider 延迟 **NOT RUN**。首次摘要请求额外消耗不能由这些估算值推断净节省。

## 本地验证与历史约束

- 新测试 `server/tests/test_context_gate_b.py`：23/23 PASS；全量 `server/tests`：263/263 PASS。`PYTHONDONTWRITEBYTECODE=1`，复用已有 Python 3.14 `.venv`，不安装包。全量测试中的既有 Issue #12 用例需在独立 Worktree 的 `.local` 写临时目录，因此在 Host 文件权限下执行；第一次 Sandbox 尝试因该目录写权限失败，不能当作代码失败。
- Ruff：`server/src`、`server/tests`、Gate B 脚本及原 CI 相关脚本全部 PASS。`scripts/check_issue11_manifests.py` PASS。独立 Compose 项目名 `kube-triage-issue28-gateb-real` / `kube-triage-issue28-gateb-test` 的 `config --quiet` PASS，仅解析，未启动容器或创建卷。`git diff --check` PASS。
- 本轮真实 Provider Run 0，Kubernetes 写 0；`REPAIR_ENABLED=false`。不读取生产 Key/Token/日志，不改 Reader、Repair、RBAC、Namespace、数据库或旧 Checkpoint。
- #11 严格 CrashLoop Gate FAIL / 人工 BLOCKED、#13 G03 PARTIAL FAIL / L3 NOT RUN、#15 B06 FAIL 保持原历史结论。

## 交付后续

本次 [Gate B Draft PR #30](https://github.com/Vc-great/kube-triage-agent/pull/30) 的 CI 最终结论待核对；正式独立 Review 当前提交数 0，记 `PENDING/NOT RUN`。保持 Draft，禁止自动合并或关闭 Issue #28。真实模型 Smoke/A-B 需另行批准合成数据、Mock-only 拓扑、请求与费用预算、受保护传输；在此之前只能声称离线协议与安全边界已验证。
