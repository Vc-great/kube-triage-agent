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
| A10 交付 | BLOCKED | 中文设计/验收/面试文档与 Draft PR 按交付流程提交；PR、最终 HEAD、CI 以 PR 页面及最终回报为准，不在提交前编造。 |

## 脱敏协议轨迹与故障

正式隔离 Compose 拓扑中，`scripts/issue41_phase_a_smoke.py` 两轮返回 Thread `7e821771-d8c0-4cd6-b1dc-3648d60701ba`、Run `5e5ab16f-e72d-4fe0-a966-201dbaf4d750` / `043b6a0d-8935-4d69-8ec2-e188e16171f7`，消息类型为 `human,ai,tool,ai,human,ai,tool,ai`；两个 Tool Call ID 与 ToolMessage ID 一一对应，History 10 项。服务重启后相同 Thread 的 Checkpoint ID 为 `1f1ca3e5-c0b5-6ef2-800c-fd1cf5d209bc`，State 保留 8 消息；第三轮 SSE `end: success`，State 12 消息、3 次调用与 3 个回执。状态中只有合成输入与 Mock Event。

首次探索性 Smoke 使用了继承 `ChatOpenAI` 的测试类，仅覆盖 `_agenerate`，Aegra SSE 走到未覆盖的流式 Provider 接口，返回 `OpenAIAuthenticationError` 与 `end: error`。当时只有合成问题、无效合成 Key；未使用任何真实集群/有效模型凭据。发现后立即停止 Aegra，将测试类改为独立 `BaseChatModel`，同时覆盖 `_agenerate` 与 `_astream`，增加流式单测，并在正式 Compose 拓扑重跑成功。探索性独立容器/卷已按明确名称删除；该失败不能抹去，也不算成功协议证据。

复现协议 Smoke 的关键命令：先设置合成的 `ISSUE41_DB_PASSWORD`，执行 `docker compose -p kube-triage-issue41-phase-a -f infra/issue41.phase-a.compose.yaml up -d --wait`；在 `TRIAGE_ENV=test`、`MOCK_MCP_HOST=127.0.0.1` 下启动 `python -m kube_triage.mock_mcp`；以 `env -i` 明确传入测试环境变量，令 `DEEP_DIAGNOSIS_FAKE_MODEL=true`、`MCP_SERVER_URL=http://127.0.0.1:8000/mcp`、`OTEL_TARGETS=`、`POSTGRES_PORT=15441`、`REDIS_URL=redis://127.0.0.1:16341/0`，运行 `aegra serve --host 127.0.0.1 --port 12441 --config aegra.phase-a.json`；随后以同一合成测试 Token 执行 `scripts/issue41_phase_a_smoke.py`。重启 Aegra 后查询上述 Thread 的 `/state`，再在该 Thread 上发第三轮 Run。不得在有真实 `.env`、真实 Provider Key 或端口归属不明的环境直接复现。

## 范围与结论

没有真实 Kubernetes 读写、真实 Provider 成功调用、Langfuse Cloud 发送、旧生产 Checkpoint 迁移或稳定服务操作。第一次合成数据测试意外进入 Provider 客户端路径；外部是否收到该请求无法证明，故 A08 留 FAIL，不以修复后的成功覆盖失败记录。Model Profile 在真实模型、Prompt Injection 语义、Run 取消/重连和稳定环境旧 Thread 仍有证据缺口，Phase A **NO-GO**，不建议仅凭当前 PoC 进入 Phase B。首选修复方向：在同一隔离 Aegra 拓扑补充可审计的取消/重连与真实模型工具披露证据；真实 Provider、真实 Reader 和数据外传必须另行授权。若保持零 Provider 成本，可先用更强的 FakeModel 合成注入/UID 用例收紧执行与答复契约。
