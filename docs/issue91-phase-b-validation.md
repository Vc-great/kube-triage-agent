# Issue #91 Phase B：离线实现与待运行验收

权威标准：[设计 §5](plans/issue-91-observability-fault-lab.md#5-唯一权威验收-gate全部初始-not-run)。本报告记录证据，不替代 Gate。

**当前结论：Phase B BLOCKED，Implementation PR 保持 Draft。** 本轮私有配置绝对路径尚未获授权；orchestrator 已明确要求仅完成离线工作。未读取或复制其他 Worktree 凭据。真实模型 **0/10 Agent Run**，并发 0；S04–S08 各剩余最多 2 Run。本轮没有真实模型响应、Cloud API 请求、Cloud Trace URL 或重复调用事件结果，不将离线替身当成真实模型证据。不关闭 #91，不实施 #92，不自动合并。

## 基线与前置条件

2026-10-27 执行 `git fetch origin`，`origin/main=91590c074363377d0cde62f771cf02efe5a7c29a`。使用独立 AO Worktree `kube-triage-agent-27`，从该 SHA 创建 `ao/fault-lab/phase-b`。工作区最初干净。Planning PR #93、Phase A PR #94/#95 均已合并；[#95](https://github.com/Vc-great/kube-triage-agent/pull/95) 与[Phase A 实测报告](issue91-observability-lab-validation.md)确认 A0–A5 PASS，含实际 Cloud 完整链和 CI。设计顶部 Proposed 为历史描述，不据此推翻已合并事实。PR #90 属于其他工作，未修改其分支或资源。

Host 能力检查确认 Python 3.13.14、uv、两张锁定 Docker 镜像已存在；`uv sync --frozen --offline --python 3.13` 从本机缓存创建本 Worktree `.venv`，未升级工具/锁文件。Aegra 0.10.8、LangGraph 1.2.14、langchain-openai 1.7.0、OpenAI 3.29.0、OTel 1.45.1。既有 `kta-issue78-pg` 未动。本轮未创建 Docker 容器，离线测试的独立子进程均已结束。

## 已实现范围

- S04：Mock 对 `sample-a` 的合法 `pods_log` 延迟 8.2 秒，实际 Reader 仍按原 8 秒超时返回。
- S05：Mock 对 `sample-a` 的 `pods_get` 抛出合成 `403 Forbidden` 工具错误，经 MCP/Adapter/Reader 分类为 `forbidden`，实验业务标签为 `permission_denied`。这是 MCP 工具错误中的合成权限拒绝，不宣称 Mock HTTP 层返回了 403。
- S06：Mock 的 `pods_log` 正常返回内层 `ok=false`，Reader 仍保持正式外层 `ok=true`。测试观测将其分类为 `business_error`，不改变原返回值或正式 Graph 的 ToolMessage 状态语义。
- S07：仅回环监听的测试桩，首请求合成 429，随后仅转发至原已批准 Provider 的固定 `/v1/chat/completions`。不跟随重定向，不继承代理，不关闭 TLS 校验，不记录 Header/Body。每批仅 1 Run，最多 8 HTTP attempt；原 SDK `max_retries=1`、30 秒模型请求超时、4 次模型决策/6 次工具执行不变。编号 attempt 记录合成 429 与转发状态；实际 Provider 200、Run 和完整 Cloud 链均满足才可认定恢复。离线客户端重试测试使用明确的本地替身响应，不能证明真实 Provider 恢复。
- S08：只提示模型在必要时确认瞬态变化，不生成/修改模型 Tool Call。按实际工具名和规范化参数计算重复次数，保留 Call ID、模型决策阶段；未触发时事件结果为 `NOT_TRIGGERED`。重复是否不必要、模型动机不能仅由次数推断。本轮未运行真实模型，因此事件结果为 **NOT RUN**，不能填写 NOT_TRIGGERED。
- 实验 API 将实际 Reader 调用包装为 `reader_outcome` LangChain Runnable，由原生 OpenInference callback 创建业务 CHAIN 子 Span并传播父链；复用 Aegra 的同一个 TracerProvider/exporter，原生 Tool/Generation 不重复上报。只记录工具名、实际 Call ID、业务分类和 wrapper 状态，不新增原始证据正文。正式 API 入口、Reader 策略、Repair/HITL、Checkpoint、Memory/SSE 均未修改。
- Runner 将协议、业务结果、Trace 完整性分别记录。S04–S06 允许预期故障导致证据不足；仍要求故障实际发生、无其他错误、合法工具、State/History 配对及最终回答，不能仅凭注入成功判整个实验通过。最终回答的实际不确定性还需真实实验复核。
- 保留 Phase A 全部完整链校验；Phase B 额外逐 Call ID 匹配 Cloud 业务输出，并验证业务 Span 是对应原生 Tool 的祖先。缺根/Generation/Tool/业务 Span、错误参数/ID/业务标签或父子关系均不得通过。只有从同一认证 Cloud 项目实际返回的 Trace ID 才生成 URL；未查询到的不拼接链接。
- 每批一个场景、最多两 Run（S07 每批一 Run），并发 1；Phase A 原最多 6 Run 边界保留。私有 `manifest.json`、State/History/Cloud 数据与 `index.md` 位于 Git 忽略目录，继承 0700/0600。新增模型客户端 HTTP 日志计数；无可观察请求时为 NULL，Provider 内部调用数为 UNKNOWN，不估算费用。

## 逐 Gate

| Gate | 状态 | 当前证据及剩余条件 |
| --- | --- | --- |
| B0 | PASS | 确定性 Fixture 与实际本地 MCP HTTP → Adapter → 原 Reader 的 S04/S05/S06 集成测试通过；8s/16KiB/Namespace/白名单未改。仅证明合成注入与合法 Reader 路径，不证明真实模型选择工具 |
| B1 | BLOCKED | 本地 timeout/permission_denied/business_error 分类与业务 Span 契约通过；尚无对应真实 Cloud Observation/URL，不能 PASS |
| B2 | BLOCKED | 本地固定目标/首次429/原客户端一次重试测试通过；真实 Provider attempt/恢复和 Cloud Trace NOT RUN |
| B3 | BLOCKED | 确定性重复度量与默认 tail 规范化测试通过；真实模型请求/响应 NOT RUN，无真实事件结果 |
| B4 | BLOCKED | Phase A 真实链接见其独立报告；本轮 S04–S08 未启动，Cloud 状态均 unknown、链 NOT RUN，无新 URL。索引不伪造缺失链接 |
| B5 | BLOCKED | 离线回归结果见下；尚缺真实实验、Cloud Gate 和最终 CI/独立评审。保持 Draft，不关闭 #91 |

## 离线验证

```sh
cd server
uv sync --frozen --offline --python 3.13
uv run --frozen ruff check src tests ../scripts/obs_lab.py ../scripts/obs_lab_api.py ../scripts/obs_lab_verify.py ../scripts/obs_lab_faults.py
uv run --frozen pytest -q tests/test_obs_lab.py tests/test_obs_lab_faults.py
uv run --frozen pytest -q
cd ..
git diff --check
```

第一轮完整回归：**939 passed、44 skipped，168.57 秒**，发生在后续观测包装/客户端重试/索引测试补充前。最终完整回归 **950 passed、44 skipped，165.49 秒**；随后收紧目标故障匹配和 S07 恢复判定，并补7项规则测试，其9项相关定向测试通过。最终全部 Phase A/B 定向测试 **72 passed，13.49 秒**。Ruff/diff check 通过。Skipped 不算 PASS。首轮 [CI](https://github.com/Vc-great/kube-triage-agent/actions/runs/40443685657) 五项通过，Python 因两个新脚本的 import 分组失败；本地根目录 Ruff 未复现该工作目录差异，随后在 `server/` 下按 CI 原命令复现并修复，完整 Ruff 命令通过。最新 CI 与独立审查结果待回查，不把首轮失败改写为成功。Sandbox 禁止回环绑定时保留了 PermissionError 反例，随后在 Host 重跑离线测试通过，未据此降低验证要求。

## 获得本轮授权配置后才可执行

以下只是复现步骤，**本轮尚未执行**。先确认配置文件当前用户持有、普通文件、0600，解析时忽略已注释旧配置；不复制源文件，不输出配置值。当前仅允许原 Provider 精确 URL 和 Langfuse Japan，API 导出沿用 Phase A 专用回环代理 33210；若任一能力或项目身份异常立即停止。不得通过新 endpoint/新账号/新代理绕过缺失授权。

```sh
# 每次先审查上次结果，确认未达到 STOP。此命令每次只产生1个新Run。
make obs-lab-phase-b OBS_LAB_ENV=/absolute/path/to/authorized-private.env OBS_LAB_SCENARIO=S04
# 分别将场景改为S05、S06、S07、S08；每场景最多执行两次，总计最多10 Run。
# 不用自动循环；失败不自动补跑。Cloud缺链只能有界只读回查，不重放付费Run。
```

先运行 S04 一次验证新增业务 Span 的真实 Cloud 表示与完整父链，再逐场景执行；S07 必须保留 attempt=1/429、后续实际 Provider 请求及是否恢复。若 Cloud 表示不兼容，先保留失败记录并修复校验，不能放宽完整性或伪造 Trace。模型未重复调用时记录 NOT_TRIGGERED，保留真实轨迹，不追加超预算调用来追求重复。

## 隔离、回退与残余风险

所有离线模型响应均明确作为测试替身，不生成真实 Run/Trace。没有读取真实集群数据、kubeconfig、私有历史，没有 Kubernetes 写入、Repair 或外部数据发送。正式入口不启用测试包装；回退本 PR 即移除新实验行为。仅清理本次创建的资源，禁止全局 down/prune。

尚未验证：Cloud 对新增业务 Span output/metadata 的实际表示、Aegra 云端导出后的原生 LangChain Span 与业务 Span 的父链、各场景模型自主工具选择、真实 429 恢复、S08 自主重复调用。离线父链/契约测试不能替代这些证据。须收到本轮配置路径授权并实际验收后才能完成 Phase B。


## 首轮原生审查修复

AO 原生审查对首个代码 head 提出两项有效问题，均在离线范围修复：

1. P1：原手工 `start_as_current_span` 不符合锁定 OpenInference 的 LangChain callback 父级选择机制，会把业务 Span 分离到另一 Trace。改为实际执行的 `reader_outcome` Runnable，内部调用原 Reader，Runnable 仅返回脱敏业务摘要，外部仍返回原 payload。实际锁定 instrumentor + Runnable + StructuredTool 的离线集成验证单 Trace、`tools → reader_outcome → pods_log` 父链、输出不含额外 result 正文及关闭 OTel 后返回值不变。旧手工嵌套测试已替换，不能用其先前通过作为真实父链证据。
2. P2：同一 Generation 中同名同参数不同 ID 的两个真实调用，不能仅靠名称/参数/时间窗区分。Phase B 匹配器先由业务 Runnable 的实际 Call ID 和原生 Tool 祖先链缩小候选，再保留原完整根/Generation/Tool/时间与 State/History 校验。增加同轮重复完整 Cloud 合成样本，以及错误 ID/父链/缺业务 Span 负例。不修改 Phase A 匹配条件，不放宽 Trace 完整性。

这些修复只证明离线机制，仍没有真实 Cloud 证据。B1–B5 保持 BLOCKED；真实模型0/10、Cloud0请求。


审查修复后的代码 head `f62d7c8`：`server/` 下完整 Ruff 命令及 diff check PASS，全部 Phase A/B 定向 **76 passed（14.06秒）**，完整后端回归 **961 passed / 44 skipped（177.95秒）**。其 [CI](https://github.com/Vc-great/kube-triage-agent/actions/runs/40444429515) 在本次报告更新时仍运行中，最终 CI/原生复审状态见 [PR #96 checks](https://github.com/Vc-great/kube-triage-agent/pull/96/checks) 与 PR 最新验收记录；此处不预判通过。两项已修复的审查线程已标记 resolved，不等同复审批准。真实模型与 Cloud 调用继续为0，PR保持Draft。
