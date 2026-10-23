# Issue #78 Phase 3：实施与验收记录

唯一设计与 Gate：[issue-78-phase3-integration.md 第 6 节](plans/issue-78-phase3-integration.md#6-phase-3-唯一权威-gate不得预填-pass)。本文件只记录实际证据，不增加或降低 Gate。Phase 1/2 的历史记录见 [原报告](issue78-validation.md)，真人 M5 没有被本报告改写。

## 基线、环境与范围

- 2026-10-23：Host `git fetch origin`，`origin/main=e78e9225e43d1749be9fca59ea86d2ce06d811d4`；#81/#83/#84 已合并，#80 Closed / Not merged，#72/#75/#78 仍 Open。Issue 正文中部分“待合并”状态已过期，以实际 PR 状态为准。
- 使用 AO 提供的干净独立 Worktree，从上述 `origin/main` 创建 `ao/graph-persistence/phase3`。没有覆盖其他工作树、重复建设 Evidence/History 表/API/前端 Hook。
- macOS arm64，Python 3.14.6；锁文件 Aegra API/CLI 0.10.8、Deep Agents 0.7.28、LangGraph 1.2.14、SDK 0.4.6、psycopg 3.3.6；Web Next.js 16.3.8、SDK 1.12.0、Node 24.20.0、项目 pnpm 10.5.1。`uv sync --frozen --offline` / `pnpm install --offline --frozen-lockfile` 复用本机缓存，无依赖升级。
- Host 先检查镜像、容器、端口。复用已有 `pgvector/pgvector:0.8.7-pg18-bookworm` 镜像，新建本任务 `kta-issue78-p3-pg` 容器/卷、AO session 标签、loopback `15488`。避开旧 PG `15478` 和已有 API/Web `12079/13078`；本任务使用 API `12089`、Web `13088`、Mock MCP `8000`。未操作未知服务。
- 全部数据为合成。无真实 Provider、Kubernetes 写入/Repair、RBAC 修改、敏感数据外传或稳定部署变更。HITL 的写操作只调用测试内的 Mock 函数。

## 逐 Gate 结果

| Gate | 结果 | 实际证据 / 限制 |
| --- | --- | --- |
| P3-G0 基线 | PASS | 最新 SHA/Issue/PR 已核对；独立 Worktree/PG/卷/端口；差异仅 Phase 3 桥接、Profile、测试和文档。原迁移、查询 API、正式 Graph 和 History Hook 未重写。 |
| P3-G1 Evidence 来源 | PASS（Mock） | `test_phase3_persistence.py` 让三个 Graph 各经过真实锁定 SDK 的 middleware → StructuredTool coroutine → `mcp_client.call_tool` → 原 Writer → PG：两 Thread 并行、每轮两并行调用，同名 Tool Call ID 仍正确区隔；403/Timeout、六次预算/第七次拒绝；每图 12 行归档，离线两调用只执行两次、无 ID。HTTP 三实验 Graph 来源字段也逐行对上；Skills `read_file`/Todo 不入 Evidence。取消/异常恢复 ContextVar。 |
| P3-G2 Profile/API | PASS（Mock） | `test_phase3_protocol.py`：真实 B1 2 PASS / 1 SKIP、Skills 1 PASS / 2 SKIP（另一个 Profile 的图明确跳过）。原 History sync/list、Evidence GET、Graph/Thread SQL、匿名 401/403；同一 Aegra app 内回读 State。正式原协议 3 PASS；连同原 SQL 测试 11 PASS。启动器 ON 1 PASS / 2 SKIP，OFF 1 PASS：原 Skills 协议完成四类输入与普通多轮，业务路由 404、Reader 不含归档字段。 |
| P3-G3 历史与流式 | 部分 PASS；控件 UNKNOWN；真人 NOT RUN | HTTP/PG 两轮、分页、重复 sync、跨 Thread、re-entry、SSE join/reconnect、失败/取消、原父 checkpoint regenerate 通过；5 项现有 Web 合并/动作测试通过。AO Browser 的首个 Skills Thread 两轮/Timeline/同步提示/显式刷新通过，SQL 为四条可见聊天和四份 Evidence。刷新后的新 Thread 按钮交互及后续问候未获可靠完成结果，记 UNKNOWN；显式无 threadId 导航显示空白新会话。真人操作未执行，M5 保持 NOT RUN。 |
| P3-G4 原 Agent | PASS（Mock + PG） | `test_phase3_agent_pg.py` 6 PASS：Summary 成功/Timeout 均保留原 Checkpoint 消息及 History ID，只缩小模型输入；真实 PG Checkpointer 重建 Graph 后恢复 Memory approve/reject、写读撤销；HITL approve/reject，只有 approve 调一次 Mock 写函数。原全量回归同时通过。没有以 InMemory 结果冒充此 PG 验证。 |
| P3-G5 Reviewer | PASS（现有 S1） | 原 S1/执行来源测试 + 12 项带持久化 metadata 的成功/403/Timeout × 有/无签记 × 归档成功/失败回执。只有当前轮 HMAC 才进入 manifest；DB ID/`evidence_persisted` 无法替代签记；错误回执不可支持诊断。无 DB 可信来源整合、无新 Reviewer Profile、未推进 #72 S2/S3。 |
| P3-G6 PG/留存/回退 | PASS（隔离测试） | 仅 stop/start 本任务 PG：Reader 一次成功但归档失败，`evidence_persisted=false`；业务 History 503；恢复后原 Evidence/History 行及数量摘要完全一致，原迁移复跑两次未改变数据。默认开关 OFF 与显式 ON 均验证；留存/备份/需另行授权的手动清理见 Demo。未删表/清卷/改 Aegra 表。 |
| P3-G7 工程交付 | 本地 PASS；CI/Review 待记录 | Ruff、全量 Python、Web lint/build、现有 5 项 History 测试、`git diff --check` 通过；CI 增量复用原 persistence job。PR、最终 CI 与 AO Reviewer 结果在后续补记；不能据此称全部 Phase 3 Gate 已满足。 |

## 可复现命令与结果

在 [Demo](issue78-demo.md#phase-3跨-graph-复用) 建立独立 PG/Mock/FakeModel 环境；以下占位符只指该测试库/该次生成的测试凭据，不应填正式配置。

```text
server/: uv sync --frozen --offline
apps/web/: pnpm install --offline --frozen-lockfile
server/: uv run --frozen ruff check src tests ../scripts/skills_demo.py
  All checks passed!
server/: ISSUE78_TEST_DATABASE_URL=<isolated-db> uv run --frozen pytest -q
  898 passed, 7 skipped in 188.62s
  SKIP 为未显式启动的 HTTP Profile；以下单独运行补足对应协议证据。
server/: ISSUE78_TEST_DATABASE_URL=<isolated-db> uv run --frozen pytest -q
  tests/test_phase3_persistence.py tests/test_deep_diagnosis_phase_a.py tests/test_deep_diagnosis_planning.py
  80 passed in 10.26s
server/: ISSUE78_TEST_DATABASE_URL=<isolated-db> uv run --frozen pytest -q
  tests/test_phase3_agent_pg.py tests/test_deep_diagnosis_review.py
  90 passed in 42.45s
server/: DATABASE_URL=<isolated-db> ISSUE78_TEST_API_URL=http://127.0.0.1:12089
  DEMO_API_TOKEN=<test-key> uv run --frozen pytest -q tests/test_app_persistence.py tests/test_app_protocol.py
  11 passed in 12.99s（正式 Fake Profile）
server/: DATABASE_URL=<isolated-db> ISSUE78_PHASE3_PROFILE=b1
  ISSUE78_TEST_API_URL=http://127.0.0.1:12089 DEMO_API_TOKEN=<test-key>
  uv run --frozen pytest -q tests/test_phase3_protocol.py
  2 passed, 1 skipped in 2.35s
server/: 同上，Profile=skills，启动独立 Skills API
  1 passed, 2 skipped in 2.11s
apps/web/: pnpm lint
  0 errors / 18 existing warnings
apps/web/: NEXT_PUBLIC_APP_HISTORY_ENABLED=true NEXT_TELEMETRY_DISABLED=1 pnpm build
  编译、TypeScript、产物生成通过（既有 Tailwind module-format warning）
apps/web/: pnpm exec playwright test tests/conversation-history.spec.ts --output <tmp-dir>
  5 passed (1.2s)
git diff --check
```

数据库故障实测步骤：先只读保存一份 Evidence、一个 Conversation 和 Evidence 总数的摘要；`docker stop kta-issue78-p3-pg`；通过原 `call_tool` 路径执行一次合成 Reader，确认调用计数=1/ok=true/归档=false，并用 ASGI 调原 History route 得到 503；`docker start kta-issue78-p3-pg`、等待 `pg_isready`；回查摘要相等；显式原迁移两次后再比对相等。没有循环重打 MCP，也没有清理数据。该步骤只允许用于自己创建的隔离 PG。

启动器额外实测：`python3 scripts/skills_demo.py --no-web --persistence --api-port 12089 --db-port 15489` 启动后跑 Skills 业务协议，1 PASS / 2 SKIP；Ctrl-C 清理本次临时容器后不传 `--persistence` 重启，运行 `test_skills_protocol.py` 为 1 PASS。首次 ON 暴露 PG 临时 Unix socket 初始化服务提前被 `pg_isready` 命中；已将原就绪检查改为 TCP `-h 127.0.0.1`，复跑 ON/OFF 均通过。没有新增归档重试。

## SDK Smoke、偏差与未完成项

- P3-A 修改前运行最小探针：`ToolCallRequest.runtime.config` 顶层包含 callbacks/configurable/metadata/recursion_limit/tags；`configurable.thread_id=p3-smoke` 实际可读。中间件设置的 ContextVar 在一次异步 yield 后仍可从 StructuredTool coroutine 读取，退出为 None。没有用猜测的调用时序标 PASS；后续 HTTP/PG 又逐行验证实际来源。
- Graph ID 固定在 Host 边界类。Skills 继承 Planning 的一次共享执行包装，Reviewer 也只绑定自己的 Graph ID，防止继承后被错标为 Planning；未改签记、授权或 Reviewer 执行逻辑。显式传给 Writer 的 Thread 优先，缺失时使用上下文；缺失 Runtime/Run ID 留 NULL。
- 两个 experimental Profile 复用现有 `http.app`/认证；正式 `graph.py`、`app_routes.py`、迁移、`mcp_client` 策略和 Web Hook 没有改动。没有新 Checkpointer、存储服务、自动清理或性能平台。每次归档仍短连 PG，少量协议用例约 2–3 秒，尚无实测理由引入 Pool/队列。
- 第一版 PG Memory 测试使用非系统身份，被既有单用户规则正确拒绝。修正为原 `demo-user` 和精确审批字段后通过；未放宽身份/审批校验。
- AO Browser 首轮完成后观察到 `read_file`、四 Reader 及 Evidence ID，第二轮普通历史/刷新后可回查四条业务消息。某些 AO 辅助命令出现 `get text` 缺参、`--state` 被工具拒绝；新 Thread 的 click/focus/Enter 后快照未确认导航，后续问候等待超时。没有足够证据认定这些交互完成或定位到产品缺陷，保留 UNKNOWN，交给真人步骤复核；未为了制造 PASS 修改 Hook。
- 真人 M5、真实模型质量、真实 Kubernetes、旧 Skills pin Checkpoint Resume 均未执行/不在本次自动回归结论内。Issue #78 保持 Open，PR 不自动合并。

## PR / CI / Review 补记

- Implementation Draft PR：[#85](https://github.com/Vc-great/kube-triage-agent/pull/85)，初始实现 `757eaf7`；保留真人 NOT RUN 和浏览器控件 UNKNOWN，不关闭 #78。
- 首次 CI [run 39875223606](https://github.com/Vc-great/kube-triage-agent/actions/runs/39875223606)：Web/Skills/Compose 通过；persistence 前 21 项 PG/正式协议测试通过，切 B1 后 Graph 请求 404，**该 job FAIL**。根因是仅杀 `uv`/Aegra 启动 PID，没有结束 `aegra serve` 派生的 Uvicorn，健康检查命中了旧正式 Profile。
- 最小 CI 修复：用独立进程组启动/退出每个 API；实验就绪检查除服务可用外，核对认证后的 `/assistants` Graph 集合。未改应用 Graph/Checkpointer；本机先前 HTTP Matrix 使用进程组整体退出已通过。新 head 的 CI 和独立 Review 结果待追加。

- 第二轮 CI [run 39876177880](https://github.com/Vc-great/kube-triage-agent/actions/runs/39876177880)：正式/PG 21 项再次通过，旧端口已释放；实验就绪检查 FAIL。独立 B1 HTTP 探针证实 `/assistants` 会返回共享 PG 中之前 Profile 的持久记录（Agent/Deep/Planning/Skills），因此严格集合相等误判。修正为包含预期 Graph，随后仍执行真实 Run 与 SQL 来源验证；不是降低执行 Gate。
