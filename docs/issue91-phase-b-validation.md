# Issue #91 Phase B：真实验收报告（含历史 STOP）

权威标准：[设计 §5](plans/issue-91-observability-fault-lab.md#5-唯一权威验收-gate全部初始-not-run)。本报告记录实际证据，不替代或放宽 Gate。

## 2026-10-27 本轮结论：PHASE B BLOCKED

**S04 已真实运行，触发 8 秒 Reader timeout，模型正确说明日志缺失；Cloud 已回查真实 Trace，但缺少超时原生 `pods_log` Tool Span，完整链 BLOCKED。按 STOP 条件停止，S05–S08 NOT RUN。** 本轮只使用 **1/10 Agent Run，并发 1**，无第二次 Run、无自动补跑。没有放宽验收、补发/伪造 Observation 或改写历史失败。未修改运行代码、SDK、锁文件或正式安全边界；不实施 #92，不关闭 #91，不自动合并。

### 基线、授权与隔离

- 执行 `git fetch origin`，基线 `origin/main=16a9925277d67d4e7331f52aa7e895590bf58147`；#94/#95/#96 已合并。权威计划顶部 Proposed 为历史描述，已合并事实及 Phase A 实证见 [Phase A 报告](issue91-observability-lab-validation.md)。A0–A5 的既有 PASS 未被本轮重新运行。
- 独立 Worktree：`/Users/vc/.codex/worktrees/issue91-phase-b-validation/kube-triage-agent`。原工作区 `server/src/kube_triage/graph.py` 的未提交修改未动；开放 PR #90 属于其他工作，未操作其分支或资源。
- 本轮用户明确授权读取的唯一配置源：`/Users/vc/code/kube-triage-agent/.env`。只先检查文件属性：存在、普通文件、非符号链接、属主为当前用户、权限 `0600`，符合 Runner 要求；随后仅由现有配置解析器在内存中读取。未搜索其他私有配置，未复制、修改、打印或提交该文件/密钥。
- Provider 精确为 `http://192.168.31.110:8317/v1`；只读 `/models` 返回 HTTP 200，配置 `gpt-6-luna` 在模型清单中。真实 Run 回显同名模型。API 子进程沿用 `http://127.0.0.1:33210`，内网 Provider/回环走既有 NO_PROXY；不修改系统代理。33210 TCP 可达。
- Cloud `GET /api/public/projects` 返回唯一项目 `cmvpzre7e002pad0evz874brn`，与 Phase A 已验证项目完全一致；仅 Japan。Cloud 客户端沿用现有直连只读策略，不继承 Host 代理。Trace `public=false`，查看链接需要该项目账号权限。
- 本轮唯一 `AO_SESSION_ID=issue91-phase-b-20261027-01a17bc7-72e840c5`。独立 PG/Redis 容器带本会话及 batch 标签；PG/Redis/API 回环端口分别为 58403/58404/58405，Mock 8000；PG 使用 tmpfs，无持久卷。`TRIAGE_ENV=test`、Repair OFF、Memory/History/Evidence OFF，未加载 kubeconfig，全部问题及 Reader 返回均为冻结合成数据。
- Host 已有 Python 3.13.14、uv、Docker Server 29.7.2 和两张锁定镜像 `pgvector/pgvector:0.8.7-pg18-bookworm` / `redis:8.4.7-alpine`。执行 `uv sync --frozen --offline --python 3.13`，只复用本机缓存，未下载或升级。
- 运行版本：Aegra 0.10.8、LangGraph 1.2.14、langchain-core 1.6.12、langchain-openai 1.7.0、OpenAI 3.29.0、OpenInference LangChain 0.1.79、OTel 1.45.1。

### 场景总览与实际预算

| 场景 | Run ID / 实际模型 | 决策 / 模型 HTTP / 工具 | 真实 Cloud Trace | 故障 / 模型行为 / Cloud / 场景结论 |
| --- | --- | --- | --- | --- |
| S04 Timeout | `01e28c4c-df91-4a95-94e6-b45c46015e23` / `gpt-6-luna` | 2 / 2（200、200） / 2 | [S04 Trace](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/9ae1ea2de58f98d9d390d5990a890295) | 注入 PASS；模型说明缺证据 PASS；协议 PASS；Cloud 完整链 BLOCKED；场景 BLOCKED |
| S05 合成 MCP 403 | 无 / NOT RUN | 0 Run；调用数不适用 | 无，未生成 | NOT RUN；不能宣称 permission_denied 的真实 Cloud 结果 |
| S06 内层 ok=false | 无 / NOT RUN | 0 Run；调用数不适用 | 无，未生成 | NOT RUN；不能宣称 wrapper_success/business_error 的真实 Cloud 区分已通过 |
| S07 首次模型429 | 无 / NOT RUN | 0 Run；调用数不适用 | 无，未生成 | NOT RUN；无 attempt、429 或真实 Provider 恢复证据 |
| S08 重复工具 | 无 / NOT RUN | 0 Run；调用数不适用 | 无，未生成 | NOT RUN；事件未运行，不能填写 NOT_TRIGGERED |

实际使用 1/10 Run，剩余 9 Run；S04 使用 1/2，其余各使用 0/2。余量不构成 STOP 后继续调用的依据。模型 HTTP 次数来自 Runner 客户端 HTTP 日志；Provider 内部请求数、计费 UNKNOWN，不以决策数估算。SDK max_retries=1、每模型请求30秒、模型决策4次/工具6次、单Run150秒、后台重试0，均未改变。本轮只有 S04 的2个模型 HTTP 200，没有模型429。

实际命令（先前置检查，再手动执行；本节不是立即重跑授权）：

```sh
AO_SESSION_ID=issue91-phase-b-20261027-01a17bc7-72e840c5 make obs-lab-phase-b \
  OBS_LAB_ENV=/Users/vc/code/kube-triage-agent/.env OBS_LAB_SCENARIO=S04
```

第一次启动批次 `issue91-20261027-131456-533f08` 在创建任何 Thread/Run 或 Docker 资源之前因8000占用被保护机制拒绝（退出2，0 Run）；当时离线真实Mock测试仍使用8000，是执行安排错误。等76项测试全部结束后，端口释放，才手动启动第二个批次。没有把失败启动隐去，也没有重放失败 Agent Run。

实际 Run 所在批次 `issue91-20261027-131523-19930d`；北京时间13:15:34.402–13:15:54.578（UTC05:15:34.402–05:15:54.578）。Thread 为 `2c10c688-4b89-445e-be9c-2eb04adb6f5b`；Run ID 与 Trace ID 分别保存，不混用。

### S04 故障、模型与本地证据

模型第1次决策自主请求下列两个合法 Reader，第2次决策完成中文回答。全部参数均为真实 Tool Call，而非 Runner 强塞。

| 工具 / 阶段 | 实际 Tool Call ID | 实际参数 | State/History 结果 | Cloud 业务结果 |
| --- | --- | --- | --- | --- |
| pods_get / 决策1 | `call_SD6DlBOCsbG2lvA5R9NUVhwN` | `namespace=kube-triage-demo, name=sample-a` | 外层 ok=true；Running、app.ready=false、restartCount=4、CrashLoopBackOff | success、wrapper_success=true |
| pods_log / 决策1 | `call_ZHhZHRft4rNVshoAMNSvVgP5` | `namespace=kube-triage-demo, name=sample-a, tail=30` | 外层 ok=false、error_type=timeout、ToolMessage status=error | timeout、wrapper_success=false |

Mock 延迟8.2秒；现有 Reader 仍8秒超时，实际审计 `duration_ms=8009`。State/History 的模型序列和每个 Call ID 请求/回执配对一致；无SSE error、无预算耗尽、无非预期工具结果。Agent Protocol 终态为 `success`，与预期 Tool Error 可同时成立。证据充分性为 false，不能当成诊断根因已确认。

模型最终明确说“读取调用超时，未取得日志”，只确认 Pod 详情支持的 CrashLoopBackOff/未就绪/重启4次，并说明缺日志、退出码、终止状态和 Events，无法判断具体退出原因。没有声称读到了日志、没有编造 APP_CONFIG_PATH 根因，也识别返回为静态 fixture；仅给人工建议，未执行修复。此结论来自 State 最终回答复核；同一最终回答也存在于 Cloud 尾部 Generation output。它不证明缺失的原生 Tool Span。

### Cloud API v2 真实结构、父链与缺失项

Runner 用同项目认证的 `/api/public/v2/observations`，按 Session 与可信 `metadata.run_id` 唯一关联，再按 Cloud 实际返回的 Trace ID 回查；限定起止窗口、每页100条、最多20页，Cloud等待120秒。结果是 **13条：2 GENERATION、1 TOOL、10 CHAIN（其中2个reader_outcome）**，完整唯一根和已返回节点无跨Run/Session/项目混属；已返回节点的祖先树与父时间覆盖通过，缺失原生工具导致整个完整链仍不通过。

| Observation ID | 名称 / 类型 | parentObservationId | UTC start → end |
| --- | --- | --- | --- |
| `619b92b57f9d5a1f` | LangGraph / CHAIN 根 | None | 05:15:34.479 → 05:15:54.456 |
| `7716ea9255da2f7b` | llm / CHAIN | `619b92b57f9d5a1f` | 05:15:34.490 → 05:15:38.769 |
| `bb51f99432fbc362` | ChatOpenAI / GENERATION 1 | `7716ea9255da2f7b` | 05:15:34.569 → 05:15:38.764 |
| `d7e13b2606bf8114` | tools / CHAIN | `619b92b57f9d5a1f` | 05:15:38.792 → 05:15:46.917 |
| `e3cb7e8fc68cdeb7` | reader_outcome / CHAIN（pods_get） | `d7e13b2606bf8114` | 05:15:38.797 → 05:15:38.901 |
| `2f8abea2fb3f25e2` | pods_get / TOOL | `e3cb7e8fc68cdeb7` | 05:15:38.799 → 05:15:38.900 |
| `854efd0d3b43cfd8` | reader_outcome / CHAIN（pods_log） | `d7e13b2606bf8114` | 05:15:38.902 → 05:15:46.912 |
| 缺失 | pods_log / TOOL | 未知，不补造 | 未知，不由本地耗时补造 |
| `3bb1ebd2876ba56a` | llm / CHAIN | `619b92b57f9d5a1f` | 05:15:46.926 → 05:15:54.383 |
| `2186a437c639a3bb` | ChatOpenAI / GENERATION 2 | `3bb1ebd2876ba56a` | 05:15:46.930 → 05:15:54.379 |

另4个原生 CHAIN（__start__、_route、两次_after_llm）保存在完整Cloud JSON，均回到同根，未在上表重复列举。两个业务 Span 都是 Cloud 实际返回的 output JSON，实际 Call ID、tool_name、tool_outcome、wrapper_success 与 State/History 一致；不是假定 Cloud metadata 存在同名字段。`reader_outcome` level 为 DEFAULT，timeout 由业务 output 标识，不谎称原生 Span ERROR。

pods_get 的完整桥已通过：Generation `bb51f99432fbc362` output Call ID → Tool `2f8abea2fb3f25e2` 的名称/参数/时间及所属业务Span → Generation `2186a437c639a3bb` input 的 ToolMessage ID。pods_log 的请求与响应IO及业务输出可见，但没有原生 Tool；不能拿业务 CHAIN 替代 TOOL，也不能凭两个Generation或根Span齐全判完整链PASS。

Runner 原始结果：`trace_verified=true`、`chain_verified=false`、`chain_status=BLOCKED`、`status=ingestion_pending`。missing 为 `all_reader_tools`、`request_tool_response:call_ZHhZHRft4rNVshoAMNSvVgP5`、`business_outcome:call_ZHhZHRft4rNVshoAMNSvVgP5`。最后一项是缺Tool桥导致business_proof不完整，**不代表 Cloud 没有 timeout 的业务Span**。

120秒等待结束后 Runner 非零退出（make退出2），原始 manifest 保留 STOP。随后仅做一次额外有界30秒只读回查，以真实 Trace ID、Run前后各60秒窗口（05:14:34.402–05:16:54.578 UTC）查询，05:18:40.795 UTC仍13条，缺失相同；单独保存后验结果，不覆盖原始失败。没有为等待摄取重放模型。

浏览器核验：**人工UI NOT RUN**。尝试应用内浏览器时建页/读取均超时，未看到项目内容；尝试当前Chrome只读打开时用户正在使用浏览器，控制被中断，停止继续操控。没有验证到有项目权限的登录态或实际Trace页面，不把API成功算成UI查看成功。

### 缺失 Tool 的本地诊断（不是 Cloud 完整链证明）

锁定 `langchain_core/tools/base.py` 的 `BaseTool.arun` 在调用 coroutine 后只捕获 `Exception/KeyboardInterrupt`，取消时的 `asyncio.CancelledError` 是 BaseException，跳过 `run_manager.on_tool_error/on_tool_end`。原 Reader 的 `asyncio.wait_for(...,8)` 取消底层工具，外层正常分类为 timeout；业务 Runnable可以结束，而OpenInference的原生Tool没有结束回调可导出。原生force_flush已completed=true、exporter failure_count=0；flush不能结束尚未结束的Span。

用相同锁定版本做了本地确定性最小复现：真实 StructuredTool coroutine sleep，`asyncio.wait_for` 在50ms取消，外层返回 `{ok:false,error_type:timeout}`，外包现有observed_reader和tools Runnable；只使用 InMemorySpanExporter，无模型、无MCP网络、无Cloud写入。结果 finished_span_names 只有 `[reader_outcome, tools]`，缺 pods_log，业务输出正确为timeout。这支持取消生命周期缺陷；不能仅凭此宣称线上导出链的全部细节已证明。

本轮遵照“运行验收 + 缺关键Span立即STOP”收尾，没有改第三方SDK、抑制取消、延长Reader超时、shield后继续执行工具或补发替代Span。后续应先针对原生取消路径做可审查的最小修复及回归，再决定S04复测与剩余场景；本报告不宣称该修复已实现，不消耗剩余预算试错。

### B0–B5 Gate

| Gate | 状态 | 本轮证据与缺口 |
| --- | --- | --- |
| B0 注入正确 | PASS | 76项离线测试含S04–S06真实本地Mock HTTP→Adapter→原Reader；本轮真实S04选中目标日志并8009ms超时，8s/16KiB/Namespace/白名单未改。S05/S06真实模型选择NOT RUN，不外推 |
| B1 错误语义 | BLOCKED | S04 Cloud业务timeout与State一致，但原生pods_log Tool缺失；S05/S06真实Cloud分类NOT RUN |
| B2 模型请求故障 | NOT RUN | S07未启动，无attempt/429/Provider恢复或Trace证据 |
| B3 重复工具 | NOT RUN | S08未启动；离线度量测试通过不代表真实轨迹，事件结果NOT RUN |
| B4 真云端链接 | BLOCKED | S01–S03既有真实链接见Phase A报告；S04有真实Cloud ID/URL但完整链BLOCKED；S05–S08无Run、无Trace，不拼假链接 |
| B5 #91收口 | BLOCKED | 真实S04 Cloud链未过，后续STOP；未达到全部必要A/B Gate。离线/既有CI成功不能冲抵 |

### 测试、CI、审计与清理

```sh
# 在独立Worktree的server/下
uv sync --frozen --offline --python 3.13
uv run --frozen ruff check src tests ../scripts/obs_lab.py ../scripts/obs_lab_api.py ../scripts/obs_lab_verify.py ../scripts/obs_lab_faults.py
uv run --frozen pytest -q tests/test_obs_lab.py tests/test_obs_lab_faults.py
# 仓库根目录
git diff --check
```

本轮 Ruff PASS，定向 **76 passed（17.51秒）**；取消最小复现得到预期失败反例，无新模型请求。完整后端回归/前端测试 **NOT RUN**（本轮仅更新验收文档，没有代码改动）。只读回查 #96 实现head `85169db4bd2f4afe95e90f1e381928a5ad1f5fd0` 的[既有CI 40444644367](https://github.com/Vc-great/kube-triage-agent/actions/runs/40444644367)：completed/success；这是既有实现CI，不代表本轮真实Cloud Gate通过。本轮报告提交的CI另记，不预判。

任务原始证据只在当前Worktree的Git忽略目录 `.local/observability-lab/`：

- `issue91-20261027-131456-533f08/manifest.json`：0 Run端口冲突失败，不删除。
- `issue91-20261027-131523-19930d/manifest.json`、`S04-1-private.json`（State/History/SSE）、`S04-1-cloud.json`、`api.log`、`mock.log`、`isolation.json`、`index.md`：实际Run与原始Cloud失败证据。
- `S04-readonly-expanded-cloud.json`、`S04-readonly-expanded-verification.json`：后验只读扩大窗口数据/校验；`offline-cancel-repro.json`：明确标为离线内存诊断。

目录0700、文件0600，原始轨迹不提交。扫描本任务12个私有文件中的源模型/Cloud凭据及Basic编码串：命中文件 **0**，只输出计数。Cloud public=false，没有扩大共享权限。API/Mock进程和本次PG/Redis容器已退出；8000、58403、58404、58405监听均已释放；既有 `kta-issue78-pg` 保持运行，未操作其他Compose、容器、卷或端口。没有真实集群读取/写入、Repair或敏感数据外发。

回退本报告只需撤回文档提交；本轮无运行代码修复。私有失败证据保留在Worktree，不归档删除。下一步在原生取消Span修复可审查后复验，当前停在Phase B，等待用户决策，不启动#92。

---

## PR #96 历史离线报告（原样保留，不代表本轮状态）

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
