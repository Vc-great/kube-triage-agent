# Issue #41 B1-R Pilot Runner Readiness（离线）

## 范围与基线

Planning PR [#53](https://github.com/Vc-great/kube-triage-agent/pull/53) 于 2026-10-20 合并，实施基线 `origin/main=335b34fb9da6b32e231929a24d37b68be3a3f03e`。从该提交新建独立 Worktree `/private/tmp/kta-issue41-pilot-readiness`，分支 `ao/pilot-readiness/runner`。Issue [#41](https://github.com/Vc-great/kube-triage-agent/issues/41) 保持 Open。

依据[阶段决策](plans/issue-41-b2-scope-and-b1r-pilot-readiness.md)和[B1-R 方案](plans/issue-41-deep-agents-real-llm-eval.md)，仅新增离线 Runner、单测与 CI lint 范围。正式 Agent、两张实验 Graph、`llm.py`、旧 `issue41_b1r_prep.py --dry-run`、冻结 `eval/issue41-b1r/` 均未修改。没有部署、真实 Provider/Kubernetes、Langfuse/OTel 外传、4 Run Pilot 或 Formal 执行。

## 实现与可核对边界

新增 `scripts/issue41_b1r_pilot.py`：复用冻结 Manifest 校验与合成 Reader 回执，选择原清单 R01/R05 的 replicate=1 四槽位进行 **SDK + MockTransport 演练**。每槽创建独立 Thread/执行 ID；顺序沿用 Manifest，不重新抽签、不补跑、不进入余下 20 槽位。OFF/ON 继续使用已合并 Graph，保留 4/10 模型决策和工具集差异。

- CLI 必须指定 `--offline-readiness`；默认零额度。`--simulate-budget` 仅配置合成预算，**没有启用 Provider 的参数或环境开关**。Transport 必须精确为 `httpx.MockTransport`，SDK 固定合成模型、占位 Key、`.invalid` 域名，不读取 `.env` 或用户密钥。
- OpenAI SDK 的 `max_retries=1` 保留在独立 Adapter 中，实际每次尝试经过 Guard；LangChain streaming、Responses、多个 generation、HTTP redirect、环境代理均禁用。Guard 在委托 MockTransport **前**同步预约单 Run/全批次请求、Token 与合成费用；失败和超时不退款。取消/异常/未知 Usage/错误模型回显/安全失败会锁存 STOP，后续 SDK 重试也无法再委托请求。
- 每次合成请求预约 `65536 input + 512 output = 66048 Token`、`0.066048 SYNTHETIC`；正文限制 65536 字节、最大输出 512。这是离线契约测试参数，**不是实际 tokenizer 上界、Provider 价格或费用授权**。真实 Usage、reasoning/cache 计费与 Provider 重试/传输契约仍未验证。失败尝试 Usage 保留 UNKNOWN；整 Run Usage 不完整时为 null，不用成功回包覆盖失败尝试的未知量。
- Guard 独立限制总/单 Run 时间；SDK 重试计入实际模拟 HTTP 尝试，模型决策另计。串行 Run；并发发送在同一事件循环内原子预约，预算检查与记账之间无 await。
- 独立 CLI 清空继承环境，显式关闭 LangSmith/OTel；全过程拒绝 socket connect/connect_ex、DNS、UDP sendto。只使用进程内 Mock Reader，仍调用原生 `validate_call`，无第二个真实 MCP Client。此进程级 guard 只适用于专用串行 CLI，不应嵌入共享 Aegra/Web Worker。
- 原始模型回包在 Graph 改写前检查：工具/参数/Namespace/ID、Reader/Todo 次数、未获证据的完成 Todo、冻结禁止断言和失败降级。最终规则另查 Graph 原始 Reader 回执、UID 冲突、Tool ID 配对与 Todo 证据错配。保留 Graph 守卫结果与 Runner 检出结果两项；Runner 检出冲突不冒充 Graph 已自行拒绝。规则不是语义安全完备证明，模型质量仍 UNKNOWN。
- 新建私有叶目录 0700，逐层 dirfd + O_NOFOLLOW 拒绝符号链接与路径穿越；文件 O_EXCL/0600，不覆盖。每槽即时保存失败/预算/Usage/原始合成回包、模型回显、版本与 SHA；只向 stdout 输出脱敏摘要。`blind.json`、`human-review.csv` 复用冻结 Rubric/CSV 字段，单独保存匿名映射，`human_review=NOT RUN`。人工评分者只接收匿名答案、合成 Reader 证据和冻结案例/Rubric，不接收映射、原始 Run 文件；Todo/表述风格仍可能间接暴露配置，不能宣称严格双盲。

## 实际验证

环境：CPython 3.14.6；`uv sync --frozen --offline` 复用本机缓存，下载 0 包；Deep Agents 0.7.28、langchain-openai 1.7.0、OpenAI 3.29.0、httpx 0.28.1。无新增依赖或锁文件变更。

在 `server/` 执行：

```sh
uv run --frozen --offline ruff check src tests ../scripts/issue41_b1r_pilot.py
uv run --frozen --offline pytest -q
uv run --frozen --offline python ../scripts/check_issue11_manifests.py
```

Ruff 与 manifests 静态检查 PASS。最终全量 pytest：**534 passed in 58.05s**；新增 Runner 的定向测试：**57 passed**。覆盖 429/500/连接错误/timeout、0/1 次请求上限、两层 Token/费用预约、4/10 模型决策、并发预约、单 Run 截止、无 Usage/错误回显、重定向/stream/多 generation/未知端点、危险工具/跨 Namespace/参数、原始不安全回答、Reader 403、UID 冲突、Todo 假完成、输出权限/路径和网络/环境恢复。

在仓库根目录执行（输出路径为每次全新私有临时目录，不提交原始结果）：

```sh
server/.venv/bin/python scripts/issue41_b1r_pilot.py --offline-readiness --simulate-budget --output /private/tmp/b1r-readiness-validation
server/.venv/bin/python scripts/issue41_b1r_pilot.py --offline-readiness --output /private/tmp/b1r-readiness-zero-validation
```

实测：合成演练 PASS，四槽、12 次模拟 HTTP、真实 Provider/Kubernetes=0；默认零额度在第一槽 STOP/request_budget，模拟请求=0，未执行后续槽。以上不是实际 4 Run Pilot。

## Gate

| Gate | 状态 | 证据与限制 |
| --- | --- | --- |
| 前置/冻结数据 | PASS | #53 已合并；实时 main、新 Worktree；原 Manifest SHA 与 24 槽、四演练槽自动校验，数据未改 |
| 请求/重试预算 | PASS（离线） | 实际锁定 SDK + MockTransport；0/1 上限；429/timeout/500/连接错误；两层预约；失败不退款；STOP 后不发送 |
| Token/费用 | PASS（合成契约） | 发送前预约与 Usage 校验、未知保留 null；真实价格/Usage UNKNOWN，不批准实际 Provider 执行 |
| 工具/Mock/安全 | PASS（规则/协议） | 原生校验复用、原始模型输出与最终证据检查、UID/注入/403/工具 ID、Todo 不充当证据；不外推真实语义安全 |
| 网络/输出隔离 | PASS（专用离线 CLI） | Transport 拒绝真实网络、socket/DNS/UDP 防线、环境清空、0700/0600/拒绝 symlink 与覆盖测试 |
| Ruff/pytest/适用 CI | 本地 PASS；远程见 PR | Ruff、534 tests、manifests 静态检查与 git diff --check 通过；首次 head 的 Python/Web/Compose 均 PASS，新 head 以 [PR #55](https://github.com/Vc-great/kube-triage-agent/pull/55) 最终 CI 记录为准 |
| 独立 Review | 最终 verdict 见 PR | 首轮两项问题已修复并补六项回归；[PR #55](https://github.com/Vc-great/kube-triage-agent/pull/55) 记录最新 head 独立 verdict，不以旧 head 结果冒充最终批准 |
| 人工盲审/模型质量 | NOT RUN / UNKNOWN | 仅提供模板与合成协议演练，不自动生成真人评分 |
| Issue B8 / Pilot / Formal | NOT RUN | 本阶段禁止真实 Provider，未执行实际 Pilot/Formal |
| B2-A / B2-B / B3 | 暂停 / NOT RUN | B2 Issue B3/B5 的既有 BLOCKED 不解除；无 B3 实施 |

真实 Provider 执行入口保持 **BLOCKED_PENDING_AUTHORIZATION_AND_PROVIDER_CONTRACT**。未来需另批 Provider/端点/TLS/出站、HTTP 尝试数、单 Run/总 Token/真实费用/价格、数据白名单及测试窗口，并验证该 Provider 的 tokenizer、Usage 与失败计费上界；此 PR 的离线 PASS 不能自动解锁。旧 Phase A A08=FAIL、Phase 3B B06=FAIL 保留。回退只需不用新脚本，无正式路径/部署/Checkpoint 迁移。PR 保持 Draft，不自动合并，不关闭 #41。

## 独立审查修复

首轮 Reviewer 指出：带 tool_calls 的正文绕过安全检查，以及 Graph 异常停止时丢失已取得的 Reader 轨迹。修复后，所有非空原始正文均参与禁止断言/无证据健康断言检查，最终降级措辞单独适用于最终回复。工具执行使用本地 inline callback 和任务 ContextVar 增量捕获实际调用参数、Tool Call ID、原始 Mock 结果、Graph ToolMessage 与顺序；并行开始、实际 Mock 执行与回执完成顺序分开记录，不假设三者相同。STOP 后仍保留 Reader 次数、UID 冲突与盲审 Evidence。Graph 与冻结输入保持不变。

新增回归包含带合法调用的恶意正文、合法中间正文，以及读取两次 UID/注入日志后分别触发安全失败、请求预算耗尽、SDK 超时的失败轨迹。定向测试 **57 passed**；全量回归 **534 passed in 58.05s**；新 head 的 CI/独立 Review 结果由 PR 最终证据记录。
