# Issue #41 Phase A 验收记录（2026-10-17）

## A00 基线与冲突

- `git status --short`：开工前原 Worktree 无未提交修改；其 HEAD 为 `bd51974007d1668a8938e2f530588f05fc64c2e4`，detached。
- `git fetch origin main` 后的完整基线：`a6a287352c1af05bc365406ddf4db6b46ee8f07e`。
- 新 Worktree：`/private/tmp/kube-triage-issue41-deepagents-phase-a`，分支 `codex/issue41-deepagents-phase-a`。原 Worktree 未用于实施。
- Issue #41 Open、#28 Open、#37 Closed、#39 Closed；相关 PR #29/#30/#38/#40 已合并。#40 的 `compose/python/web` Checks 均通过。主线已有 Timeline、Context Summary、Memory 与 Langfuse 配置，提示词中的架构描述以当前源码修正。
- 已核对 `graph.py`、`mcp_client.py`、`llm.py`、`config.py`、`prompts.py`、`context.py`、`context_summary.py`、`repair.py`、`agent_progress.py`、`incident_memory*.py`、`server/aegra.json`、`pyproject.toml`、`uv.lock`、`infra/{compose,test.compose}.yaml`、Web Stream/Thread Provider、`eval/cases.json`、`server/tests/`、`scripts/`、`docs/architecture.md` 与 `docs/issue39-langfuse-observability.md`。
- Python 3.13.14、uv 0.11.21 已在 Host；缓存中原无 deepagents。`uv add --no-sync --python 3.13 deepagents==0.7.28` 更新锁文件，`uv sync --frozen --python 3.13` 成功。锁定版本：Deep Agents 0.7.28、Aegra 0.10.8、LangGraph 1.2.14、ChatOpenAI 1.7.0、langchain-core 1.6.12、LangGraph SDK 0.4.6。
- 协议测试采用独立 Compose 项目 `kube-triage-issue41-phase-a`，仅启动 Postgres/Redis；端口 `127.0.0.1:15441/16341`，专属卷 `kube-triage-issue41-phase-a_postgres_data`、`..._redis_data`。Aegra 仅监听 `127.0.0.1:12441`，合成 Mock MCP 仅监听 `127.0.0.1:8000`。正式 Compose、make dev 与已有卷均未操作。

## Gate 矩阵

证据等级：静态代码、FakeModel、Mock MCP、Aegra 本地协议、Real Kubernetes、人工确认。`PASS` 仅代表该行列明的范围。

| Gate | 状态 | 证据等级与结果 |
| --- | --- | --- |
| A00 基线 | PASS | Git/Host 静态与隔离 Compose；SHA、Worktree、端口、卷、版本如上。 |
| A01 SDK | PASS | 安装 wheel 的函数签名与源码；`create_deep_agent()` 真实编译，Aegra 列出 `agent` 与 `deep_diagnosis`。 |
| A02 工具表 | PASS | FakeChatOpenAI 实际收到的工具名恰好四个 Reader；强制 `write_file` Graph 调用收到错误，`StateBackend.files` 空。真实 Provider 的动态 Profile 未测。 |
| A03 执行约束 | PASS | FakeModel；跨 Namespace、未知 Harness 写工具拒绝；7 个并行 Reader 仅执行 6 个，第 7 个同 ID 错误；原 `validate_call()`/tools/list/超时/截断回归测试仍通过。 |
| A04 协议配对 | PASS | FakeModel + Aegra/Mock MCP；0/1/多工具及并行 ID 单测；两轮和重启后第三轮实际 State 的 AI/Tool 数量分别 2/2、3/3。错 ID 回执转错误。 |
| A05 证据安全 | BLOCKED | 403、401、404、超时、空结果、坏回执执行层负测通过；真实模型对日志 Prompt Injection、UID 冲突与语义性错误结论尚无证据。FakeModel 固定中文答复不能证明语义安全。 |
| A06 Aegra 协议 | PASS | 独立 Compose + Aegra 0.10.8；`GET /assistants` 两 Graph；`POST /threads`、`POST /threads/{id}/runs/stream` 两轮成功；SSE 有 metadata/values/end；State 8 消息、History 10 项、Checkpoint ID 存在。 |
| A07 恢复与回归 | BLOCKED | 同一 Compose 数据卷下重启 Aegra，原 Thread State 恢复 8 消息，第三轮 Run success 后 12 消息、3 对 AI/Tool；原 Graph 代码未改，Python 全套回归通过。Run 取消、断线重连/事件重放、稳定环境旧 Thread 均 NOT RUN。 |
| A08 资源/安全 | FAIL | 静态代码、FakeModel 与 Mock MCP：无 K8s 写工具、Host FS、Repair/Memory 执行；隔离运行关闭 OTel，未读取 `.env`、kubeconfig 或真实 Pod 数据。但首次错误 FakeModel 曾以无效合成 Key 进入 Provider 路径；实际请求是否到达 Provider 为 UNKNOWN。发现后停止并改为无 Provider 客户端的 `BaseChatModel`，最终隔离协议测试无 Provider 路径。 |
| A09 工程质量 | PASS | `.venv/bin/ruff check src tests` 全通过；`.venv/bin/pytest -q` 388 通过；`git diff --check` 通过。Web 未改，Web lint/build NOT RUN。 |
| A10 交付 | PASS | 中文设计/验收/面试文档已提交；[Draft PR #42](https://github.com/Vc-great/kube-triage-agent/pull/42) 为 Open/Draft，Issue #41 仍 Open。PR 初始提交 `74253d0b0dbcc63f32baa1bca962c0ae3d5bceb0`；CI 在 2026-10-17 查询时 compose PASS、python/web PENDING，最终状态以 PR Checks 为准。 |

## 脱敏协议轨迹与故障

正式隔离 Compose 拓扑中，`scripts/issue41_phase_a_smoke.py` 两轮返回 Thread `7e821771-d8c0-4cd6-b1dc-3648d60701ba`、Run `5e5ab16f-e72d-4fe0-a966-201dbaf4d750` / `043b6a0d-8935-4d69-8ec2-e188e16171f7`，消息类型为 `human,ai,tool,ai,human,ai,tool,ai`；两个 Tool Call ID 与 ToolMessage ID 一一对应，History 10 项。服务重启后相同 Thread 的 Checkpoint ID 为 `1f1ca3e5-c0b5-6ef2-800c-fd1cf5d209bc`，State 保留 8 消息；第三轮 SSE `end: success`，State 12 消息、3 次调用与 3 个回执。状态中只有合成输入与 Mock Event。

首次探索性 Smoke 使用了继承 `ChatOpenAI` 的测试类，仅覆盖 `_agenerate`，Aegra SSE 走到未覆盖的流式 Provider 接口，返回 `OpenAIAuthenticationError` 与 `end: error`。当时只有合成问题、无效合成 Key；未使用任何真实集群/有效模型凭据。发现后立即停止 Aegra，将测试类改为独立 `BaseChatModel`，同时覆盖 `_agenerate` 与 `_astream`，增加流式单测，并在正式 Compose 拓扑重跑成功。探索性独立容器/卷已按明确名称删除；该失败不能抹去，也不算成功协议证据。

复现协议 Smoke 的关键命令：先设置合成的 `ISSUE41_DB_PASSWORD`，执行 `docker compose -p kube-triage-issue41-phase-a -f infra/issue41.phase-a.compose.yaml up -d --wait`；在 `TRIAGE_ENV=test`、`MOCK_MCP_HOST=127.0.0.1` 下启动 `python -m kube_triage.mock_mcp`；以 `env -i` 明确传入测试环境变量，令 `DEEP_DIAGNOSIS_FAKE_MODEL=true`、`MCP_SERVER_URL=http://127.0.0.1:8000/mcp`、`OTEL_TARGETS=`、`POSTGRES_PORT=15441`、`REDIS_URL=redis://127.0.0.1:16341/0`，运行 `aegra serve --host 127.0.0.1 --port 12441 --config aegra.phase-a.json`；随后以同一合成测试 Token 执行 `scripts/issue41_phase_a_smoke.py`。重启 Aegra 后查询上述 Thread 的 `/state`，再在该 Thread 上发第三轮 Run。不得在有真实 `.env`、真实 Provider Key 或端口归属不明的环境直接复现。

验收后已停止本次 Aegra 与 Mock MCP，并执行专属 Compose 项目的 `down`；只按精确名称删除 `kube-triage-issue41-phase-a_postgres_data` 和 `kube-triage-issue41-phase-a_redis_data`。未对其他项目执行清理。

## 范围与结论

没有真实 Kubernetes 读写、真实 Provider 成功调用、Langfuse Cloud 发送、旧生产 Checkpoint 迁移或稳定服务操作。第一次合成数据测试意外进入 Provider 客户端路径；外部是否收到该请求无法证明，故 A08 留 FAIL，不以修复后的成功覆盖失败记录。Model Profile 在真实模型、Prompt Injection 语义、Run 取消/重连和稳定环境旧 Thread 仍有证据缺口，Phase A **NO-GO**，不建议仅凭当前 PoC 进入 Phase B。首选修复方向：在同一隔离 Aegra 拓扑补充可审计的取消/重连与真实模型工具披露证据；真实 Provider、真实 Reader 和数据外传必须另行授权。若保持零 Provider 成本，可先用更强的 FakeModel 合成注入/UID 用例收紧执行与答复契约。

## 2026-10-18 Phase A Closure 新增证据

以下是新一轮验收，不修改上述原始 A08=FAIL，也不修改 Phase 3B B06=FAIL。开工前 `git fetch origin main` 得 `bdbdc6eda41804bbb78ad0f67274163b5e767dc3`；#42 已合并，#41 Open。新 AO 工作树分支 `ao/kube-triage-agent-2/issue41-phase-a-closure`。正式 Graph、`server/aegra.json`、Repair、Memory、原始 Checkpoint 与 Golden 均未改。证据等级：S=源码/锁定 SDK，F=FakeModel 合成测试，P=隔离本机 Aegra/Mock MCP 协议；无真实模型或 Kubernetes 证据。

| Gate | 状态 | 等级与依据 |
| --- | --- | --- |
| CL00 | PASS | S：最新 main SHA、独立 AO Worktree/分支；专属 Compose Project `kube-triage-issue41-closure-2`、localhost 12441/15441/16341/8000 事前空闲，专属卷事前不存在；正式 Graph 未改。 |
| CL01 | PASS | S/F：锁定 `deepagents==0.7.28`；Fake 实收工具表恰为四 Reader；Harness `write_file` 等执行被拒。真实 Provider Profile 未测。 |
| CL02 | PASS | F：`aafter_model` 目标守卫拦截无证据的健康断言、403/404/超时、跨 Pod/Namespace、坏 UID/状态；问候可直接回答。 |
| CL03 | PASS | F/P：测试 Fake 仅继承 `BaseChatModel`，同步/异步/流式均覆盖；socket 网络哨兵拒绝外联；实验 Aegra 仅加载 Fake Graph，无 Provider 凭据，隔离 SSE 成功。原 A08=FAIL 仍保留。 |
| CL04 | PASS | S/F：实验 Provider 入口默认抛 `ConfigurationError`，仅显式 `DEEP_DIAGNOSIS_ENABLE_PROVIDER=true` 时创建真实模型；正式配置未改且原测试通过。 |
| CL05 | PASS | F/S：`tail` 对 true、字符串整数、浮点、0、101 均拒绝；0/1/多/7 调用回归，7 次仅执行 6 次且回执 ID 对齐。四次是 Graph 模型决策数，不是 Provider 内部重试次数；本轮无 Provider 重试实测。 |
| CL06 | PASS | P：专属 Aegra Thread 两轮 SSE `end`，State 8 消息、History 10 项、Tool ID 配对；重启后原 Thread 8 消息，第三轮 12 消息和 3 对 ID。 |
| CL07 | PASS（本拓扑） | P：取消 API HTTP 200，Run 随即及 2/8 秒后均为 `interrupted`，State 仅 1 条用户消息；该合成执行停止。断线后用真实 `Last-Event-ID=...event_1` 重连，收到 event_2 起至 `end`，首事件未重放。仅证明本机 in-process executor 与 in-memory SSE broker。 |
| CL08 | PASS（确定性） | F：日志注入却断言健康、UID 冲突、错误/空/坏 Reader 回执均被守卫拒绝；真实 LLM 注入语义 NOT RUN。 |
| CL09 | PASS | F/S：`uv sync --frozen --offline` 使用本机缓存；`ruff check src tests` 通过；最终 `pytest -q` 414 passed。Draft PR #43 的 compose/python/web CI 均通过。 |
| CL10 | 待复审 | S：中文设计、验收、面试复盘更新；Draft PR #43 已创建。AO 隔离 Reviewer 首轮指出客户端伪造消息及非字符串 phase 两处需修，均已补测修复，等待新 Head 复审。Reviewer 的 GitHub inline 写入被审批策略拒绝，结论留存在 AO 审查记录。 |

本轮 Docker 镜像已缓存，未下载依赖或镜像。`env -i` 启动 Fake Aegra 与 Mock MCP，`OTEL_TARGETS=`，没有运行期 Provider 目的地或有效凭据；Python 测试的网络哨兵禁止 socket 出站。协议服务只监听 localhost。先核实容器的 `ao.session=kube-triage-agent-2` 与 Compose Project 标签，随后停止 Aegra/Mock MCP，按精确项目执行不带 `--volumes` 的 `down`，仅删除两只核实属于本轮的新卷。未操作其他项目资源。历史 A08 外联结果仍 UNKNOWN。

首轮独立审查后的负测又覆盖：外部在当前 Human 后预置 AI/Tool 假回执被 `abefore_agent` 拒绝；不可信 Pod YAML 将 `status.phase` 设为列表时只报告未核验，不再使 Run 抛出 `TypeError`。这两处均属合成确定性边界，不代表真实 Provider 语义验收。
