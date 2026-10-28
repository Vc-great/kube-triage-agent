# Issue #91 Phase B 增量修复：离线验收与后续实测交接

本报告随增量 Implementation PR 交付，不改写 [PR #97 历史失败](issue91-phase-b-validation.md)，不替代[权威设计 §3.3.1 / §5](plans/issue-91-observability-fault-lab.md)。

## 基线与范围

2026-10-28 Host `git fetch origin`，`origin/main=552f46173e63ef4894ba1a81a058d814f860a274`；GitHub API 确认 PR #98 已合并，`merged_at=2026-10-28T05:50:52Z`，merge commit 与 main 一致。独立 AO Worktree `kube-triage-agent-28`，分支 `ao/observability-fixes/phase-b`，初始干净。阅读 #91、#98、权威设计及 #97 历史报告后实施。

本轮只做实验代码和离线验证，**新增真实模型 Run=0、Cloud API 请求=0、Cloud 写入=0**。历史累计仍 **1/10 Run，剩余最多 9 Run**；S04 最多剩余 1 Run，其余场景各最多 2 Run。本轮未启动 Docker，不读取配置或凭据，不连接真实集群，不修改正式 Reader 8 秒/16KiB、RBAC/Namespace、Repair/HITL、Checkpoint、Memory、SSE；不升级 SDK、不实施 #92、不关闭 #91、不自动合并。

## 新旧字段与验收行为

| 原字段 | 当前用途 / 新字段 | 证据与限制 |
| --- | --- | --- |
| `trace_verified` | 保留：唯一运行关联的实际 Cloud Trace 与 URL | 单独为 true 不足以通过场景 |
| `chain_verified` / `chain_status` | 保留严格校验，Phase A 判定路径不变 | S04 缺 TOOL 时依旧 false / BLOCKED |
| 隐含在完整链中的业务证明 | `scenario_observable` | 独立检查业务 CHAIN、Generation 请求/回执/最终回答、Call ID/参数/时间、State/History、业务分类与回答审阅；缺证据 BLOCKED |
| 无独立字段 | `native_trace_complete` | PASS / FAIL / UNKNOWN；仅已证实 S04 timeout 取消 TOOL 可场景 PASS、原生 FAIL |
| `final_answer_present` 仅证明存在 | `diagnosis_behavior` | 显式证据审阅 PASS / FAIL / UNKNOWN，绑定最终回答 SHA-256 和审阅来源；Codex/人工来源如实区分 |
| `duplicate_event` / 本地代理记录 | `event_result` | S08 从实际调用名/规范化参数度量；未触发 NOT_TRIGGERED；S07 只有本地与 Cloud attempt/模型决策关联齐备才 RECOVERED |
| `missing` | 保留原生失败清单，新增 `scenario_missing`、`cancelled_tool_calls`、`scenario_proof`、`evidence_source` | 分开保留缺失项、Call ID、业务 Observation ID、前后 Generation ID 与来源，不把缺原生桥误写为业务 Span 不存在 |

S04 例外只覆盖本实验 `pods_log(namespace=kube-triage-demo,name=sample-a)` 的真实 timeout 回执，wrapper=false、业务耗时至少 8 秒，业务 Span 与原有 `tools` 父链/前后 Generation 时序一致；原生匹配 TOOL 确实缺失，正常工具必须完整。额外 TOOL、缺 Generation/业务 Span、错父链/Call ID/参数/分类/身份、State 回执正文不一致、最终回答不一致均 BLOCKED。不添加替代 TOOL，不抑制取消，不延长超时。

S05/S06 仍要求原生 TOOL 与业务错误双维度证明。S01–S03 继续由原有完整链 Gate 决定，Phase B 的已知例外不会用于 Phase A。

实时 Runner 没有人工审阅文件，故新 Phase B Run 的 `diagnosis_behavior=UNKNOWN`、`scenario_observable=BLOCKED`，会保留证据并 STOP，不自动开始下一批。完成回答审阅后用下述离线入口形成单独结果；不重放模型，也不回写历史 manifest。

## Langfuse 观测方式与技术依据

业务故障沿用 `reader_outcome` Runnable 的现有 OpenInference CHAIN，output 仅含 `tool_name/tool_call_id/tool_outcome/wrapper_success`。timeout、permission_denied、business_error 分别清晰分类；在同一个 callback-owned Span 设置 `langfuse.observation.level=WARNING`、脱敏 status_message 和 `fault_category/data_classification` metadata，不复制 Reader 结果正文、不改变返回值或原生 TOOL 状态。成功为 DEFAULT。

S07：代理仍只接受固定回环 `/v1/chat/completions`，首请求合成 429，后续使用原已批准 Provider，最多 8 attempt，不跟随重定向，不改变 TLS 或目标白名单。新增响应头仅返回安全的 `X-Obs-Lab-Attempt` 整数。测试 API 为原异步模型客户端配置 transport，使用 OpenAI `with_options(http_client=...)` 保留原模型与重试配置；每次真实 transport 执行包在 `model_http_attempt` Runnable 内，只输出编号、forwarded、HTTP status。分类通过业务属性区分 `synthetic_rate_limit`、`provider_forward_success`、`model_http_failure`。**首个 429 是本地合成，不代表 Provider 返回 429。** 原生 Generation 仍由原 SDK 产生；两次 HTTP attempt 不伪造第二个 Generation。

本地源码核对：langchain-core 1.6.12 使用 Runnable child config/callback parent；OpenInference LangChain 0.1.79 `_start_trace` 用 `parent_run_id` 查询现有 Span，且特意不把 callback Span attach 为 OTel current context。直接用 ambient OTel span 可能形成另一 Trace，因此沿用 Runnable callback 链，并用 `LangChainInstrumentor.get_span(callbacks.parent_run_id)` 更新已存在的业务 Span。Aegra 的同一个 TracerProvider/Exporter 不变。

官方依据：[LangChain 异步 HTTP client 接口](https://reference.langchain.com/python/langchain-openai/chat_models/base/BaseChatOpenAI/http_async_client)、[Langfuse OTel 属性映射](https://langfuse.com/integrations/native/opentelemetry)、[Langfuse level/status_message](https://langfuse.com/docs/observability/features/log-levels)。实际锁定 SDK + MockTransport + InMemorySpanExporter 测试验证单 Trace、attempt 父节点为 `llm`、一个原生 LLM Generation、429→200、无密钥/原始 HTTP body；这**不是 Cloud 实测通过**。

Cloud 校验还要求同可信 Trace 的全部 attempt output 与本地代理记录逐项一致，且按模型决策分组：首次决策 attempt 1/2，后续决策各一次；缺失、错编号、错 Trace/父链/决策分组均不得标记 RECOVERED。观测属性是否在 Langfuse Japan 实际展示，仍为后续真实运行验收项。

## 历史 S04 只读复验

2026-10-28 找到 PR #97 原始私有批次：`/Users/vc/.codex/worktrees/issue91-phase-b-validation/kube-triage-agent/.local/observability-lab/issue91-20261027-131523-19930d`。只读使用该目录的 manifest、State/History/SSE 与 Cloud JSON；未读取 `.env`，未访问模型或 Cloud。原始与后验扩大窗口的 Cloud observation 列表完全相同。

先不提供回答审阅：身份、业务 Span、Call ID/参数、回执正文、父链/时序与 State/History 均通过，唯一 `scenario_missing=diagnosis_behavior_review`，保持 BLOCKED。再由本轮 **Codex 离线证据审阅**（并非声称人工/UI 已审阅）核对最终回答：明确日志读取超时、未获取日志，区分静态 fixture 与实时状态，只依据 Pod 详情描述 CrashLoop/未就绪/重启，说明缺退出码/Events/具体根因，未编造 APP_CONFIG_PATH 或执行 Repair；Cloud 尾部回答与 State 相同。审阅记录绑定回答摘要，生成单独复验结果。

| 维度 | 新设计下的历史只读复验 | 证据 |
| --- | --- | --- |
| trace_verified | true | 原 Cloud 返回 Trace `9ae1ea2de58f98d9d390d5990a890295`，同项目/Thread/Run 唯一 |
| scenario_observable | PASS | 两个 Generation、一个原生 TOOL、两个业务 reader_outcome；两组请求/回执、业务分类与 State/History 一致 |
| native_trace_complete | **FAIL** | 原生 `pods_log` TOOL 仍缺失，Call ID `call_ZHhZHRft4rNVshoAMNSvVgP5`；未补造 |
| diagnosis_behavior | PASS | Codex 审阅来源及最终回答 SHA-256；未提供审阅时仍 UNKNOWN |
| event_result | NOT RUN | S04 不宣称运行 S07/S08 事件 |
| scenario_missing | 空 | 原严格 `missing` 三项仍保留，未改写为完整链通过 |
| 历史 STOP / UI | 原样保留 / NOT RUN | 输出独立 JSON，不覆写历史 manifest，不访问浏览器 |

原数据校验和在复验前后完全一致：

| 原文件 | SHA-256 |
| --- | --- |
| manifest.json | `9edf70dcb067ed3ed9bbe5cfcc4b9033d3647b4bbca554d2b3dc676ad5da3d17` |
| S04-1-private.json | `19439a924bb283c9c8708be98a52800c5dbdae6aa3b264eea4dbf27920b70e54` |
| S04-1-cloud.json | `ea5c89b8e7efd9998c8200cff119363f3eeb74798e212040d0aca4b4c9831cac` |

最终回答摘要为 `9c9b98d7a2f9d02829101c8acfcf4b4496f8563f670d3c5bfcb8d1b255b3491d`。原私有 JSON/完整回答与审阅文件不提交。此处是**按 #98 新设计对旧证据的独立复验**，不覆盖 #97 当时的失败或把新运行标为 PASS。

新增 `scripts/obs_lab_reverify.py` 只读取指定批次的 `manifest.json`、每 Run 的 `*-private.json`/`*-cloud.json`（S07 另读 model-attempts.json），重新计算 State/History、调用、故障和 Cloud 证据。结果必须写到历史目录外的新文件，保留原始 STOP，文件0600，不覆写任何输入。

```sh
# 从仓库根目录执行；SOURCE 是已保存的指定历史批次，绝不能指向 .env。
server/.venv/bin/python scripts/obs_lab_reverify.py \
  --source /absolute/path/to/saved-batch \
  --reviews /absolute/path/to/answer-reviews.json \
  --output /absolute/path/outside-source/new-offline-result.json
```

review JSON 以 Run ID 为 key，每项为 `{"status":"PASS|FAIL","source":"审阅人/证据依据","answer_sha256":"..."}`。摘要按 `obs_lab_verify.content_digest(final_answer)` 计算；必须先审阅 State 最终回答及工具证据边界，再填审阅结果，不能根据摘要本身填 PASS。未提供 review 时为 UNKNOWN / BLOCKED。此文件只存私有目录，不提交原始回答/轨迹。

## 离线回归

Host 已有 Python 3.13.14 与 uv，`server/` 下 `uv sync --frozen --offline --python 3.13` 复用缓存建立环境。Aegra 0.10.8、LangGraph 1.2.14、langchain-core 1.6.12、langchain-openai 1.7.0、OpenAI 3.29.0、OpenInference LangChain 0.1.79、OTel 1.45.1，锁文件未改。

```sh
cd server
uv run --frozen ruff check src tests ../scripts/obs_lab*.py
uv run --frozen pytest -q tests/test_obs_lab_phase_b.py tests/test_obs_lab.py tests/test_obs_lab_faults.py
uv run --frozen pytest -q
cd ..
git diff --check
```

最终 Ruff 与 `git diff --check` PASS，Phase A/B 定向 **115 passed（13.35秒）**；冻结最终代码后的完整后端回归 **1000 passed / 44 skipped（160.68秒）**；CI/原生评审待回查。首次 sandbox 定向 99 passed / 3 skipped / 2 failed：回环 bind 被隔离禁止；Host 重跑104 passed，补业务属性与回执校验后105 passed。补充取消复现、离线 CLI 输出权限/禁止覆盖、S05/S06 双维度、History 最终回答和决策分组后定向115 passed。一次完整回归在运行中修改模块，导致旧 Verifier 与新入口混用 ImportError（997 passed / 44 skipped / 1 failed）；该轮不计 PASS，冻结代码后重新运行完整回归。Skipped 不计 PASS。前端无变更，前端本地 lint/build NOT RUN；CI 按仓库流程核验。

## 残余风险与回退

原生取消 TOOL Span 缺陷仍存在，`native_trace_complete=FAIL` 必须继续展示。已知例外只使证据齐备的 S04 可用于分析，不代表 SDK 缺陷修复。S05–S08 新 Cloud 证据、业务属性真实映射、S07 Provider 恢复和 S08 是否触发均 NOT RUN；预算不重置。完整离线测试或 CI 通过都不能当作 Phase B Cloud Gate PASS。

回退：撤回本增量 PR 的提交即可恢复旧 Runner/Verifier/实验入口；正式服务部署无需调整。保留原私有证据和 #97 历史失败，不执行全局 Docker 清理或修改其他会话资源。

**离线准备已完成**：历史 JSON 只读复验、Ruff、115项定向及1000项完整回归已通过。是否 **READY FOR PHASE B REAL VALIDATION** 以 [PR #99 最新 CI](https://github.com/Vc-great/kube-triage-agent/pull/99/checks) 与原生评审后的最终交付结论为准；本文记录时尚在等待，不能预判 PASS。即使就绪，也不包含新增真实模型 Run 的授权。
