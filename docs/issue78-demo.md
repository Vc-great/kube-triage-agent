# Issue #78：本地持久化 Demo 操作

本 Profile 使用正式 Graph + 测试专用 FakeModel + 仓库 Mock MCP + 独立 PG18；不会创建模型 Provider 客户端或连接 Kubernetes。唯一设计与验收仍是 [已合并计划](plans/issue-78-conversation-evidence-demo.md)，实测见 [验证报告](issue78-validation.md)。正式 `server/aegra.json` 继续使用原模型和 Reader；新增功能默认关闭。

## 准备与启动

在本任务独立 Worktree 中运行。先检查 Docker/端口归属，确认 `8000`、`12079`、`13078`、`15478` 空闲；不要停止其他项目来腾端口。需要仓库锁定的 Python、uv、Node、pnpm 依赖与本机 Docker。

以下命令在**同一个终端**执行，凭据仅生成到进程环境，不输出或写入报告。Compose 项目名与卷均独立，不叠加正式 Compose，也不读取正式 kubeconfig。

```bash
export COMPOSE_PROJECT_NAME="kta-issue78-$(date +%s)"
export ISSUE78_PG_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
export DEMO_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
export DATABASE_URL="postgresql://issue78:${ISSUE78_PG_PASSWORD}@127.0.0.1:15478/issue78"
export TRIAGE_ENV=test AUTH_TYPE=custom
export MCP_SERVER_URL=http://127.0.0.1:8000/mcp MOCK_MCP_HOST=127.0.0.1
export APP_HISTORY_ENABLED=true APP_EVIDENCE_ENABLED=true
export INCIDENT_MEMORY_ENABLED=false INCIDENT_MEMORY_READ_ENABLED=false INCIDENT_MEMORY_WRITE_ENABLED=false
export OTEL_TARGETS='' OTEL_CONSOLE_EXPORT=false LANGSMITH_TRACING=false
export REPAIR_ENABLED=false REPAIR_SIMULATED=false

docker compose -f infra/issue78.persistence.compose.yaml up -d --wait postgres
(cd server && uv sync --frozen)
# 显式迁移，只创建 app_* 表，不修改 Aegra 管理表。可重复执行。
(cd server && uv run --frozen python -m kube_triage.app_storage)

DEMO_LOG_DIR="$(mktemp -d /tmp/kta-issue78.XXXXXX)"
(cd server && exec uv run --frozen python -m kube_triage.mock_mcp) >"$DEMO_LOG_DIR/mock.log" 2>&1 &
MOCK_PID=$!
(cd server && exec uv run --frozen aegra serve --config aegra.issue78-demo.json --host 127.0.0.1 --port 12079) >"$DEMO_LOG_DIR/api.log" 2>&1 &
API_PID=$!

(cd apps/web && pnpm install --frozen-lockfile)
(cd apps/web && NEXT_PUBLIC_API_URL=http://127.0.0.1:12079 NEXT_PUBLIC_ASSISTANT_ID=agent NEXT_PUBLIC_APP_HISTORY_ENABLED=true pnpm dev --hostname 127.0.0.1 --port 13078)
```

`server/tests/issue78_demo.py` 在 `TRIAGE_ENV!=test` 时拒绝导入。`/fake-fail` 与 `/fake-slow` 仅用于此 FakeModel Profile。独立测试环境不启用 Memory/Trace，正式服务的模型配置校验未被放宽。

## 浏览器手工验收

1. 打开 `http://127.0.0.1:13078`，连接 `http://127.0.0.1:12079`、Graph `agent`，在自己的终端私下取得本次生成的 `DEMO_API_TOKEN`，填入 Demo API Key。不要把凭据粘贴到 Issue、截图或报告。
2. 新建 Thread，发送“查看合成事件第一轮”。观察原 Tool Call / Tool Result 和 Assistant 合成回复。等待“历史已同步（当前分支）”。Tool Result 包含 `evidence_id`、`evidence_persisted=true`。
3. 同 Thread 发送“查看合成事件第二轮”，等待同步；应有两条 Human、两条用户可见 Assistant，工具结果仍单独展示。同样的提问也应保存为不同消息。
4. 刷新页面，再从侧栏进入同一个 Thread；四条聊天正文顺序不变，无重复泡泡，Tool/Timeline/审批控件仍由原 SDK 管理。
5. 复制本 Thread ID 和 Tool Result 的 Evidence ID，在同一终端执行下面的**只读查询**。确认 `thread_id`、`tool_call_id`、状态、截断标志和保存正文对应。保存的是本次应用收到的受限快照，不代表全量 Kubernetes 日志。

```bash
export DEMO_THREAD_ID='<浏览器 Thread ID>'
export DEMO_EVIDENCE_ID='<Tool Result 中的 evidence_id>'
curl --fail -H "X-Api-Key: $DEMO_API_TOKEN" \
  "http://127.0.0.1:12079/app/evidence/$DEMO_EVIDENCE_ID"
curl --fail -H "X-Api-Key: $DEMO_API_TOKEN" \
  "http://127.0.0.1:12079/app/history/threads/$DEMO_THREAD_ID/messages?limit=100"
```

6. 关闭 API 后刷新，或让自定义 History API 不可用，确认页面明确提示“历史尚未同步/实时消息”，不宣称保存成功；恢复 API 后重新进入 Thread 应能补同步。API 完全离线时，原连接检测可能要求重新填写 Key。
7. 发送 `/fake-slow` 后刷新以观察 SDK reconnect；发送 `/fake-fail` 验证失败 Run 的已知消息可保留，不标为完成。完整历史分支树不在本期；重生成显示当前分支，旧版本仍在业务表。仅有 DB 历史、缺少 SDK 父 checkpoint 的回复不提供重新生成，保留复制。
8. 重启**本项目**的 PostgreSQL，再查询原 ID；重复迁移不删除数据。记录真人的实际结果与环境后，才能将设计中的 M5 标为 PASS。

## 自动验证与关闭

保持测试 API 运行，在同一环境执行：

```bash
cd server
ISSUE78_TEST_DATABASE_URL="$DATABASE_URL" ISSUE78_TEST_API_URL=http://127.0.0.1:12079 \
  uv run --frozen pytest -q tests/test_app_persistence.py tests/test_app_protocol.py
uv run --frozen ruff check src tests
uv run --frozen pytest -q
cd ../apps/web
pnpm lint
pnpm build
pnpm exec playwright test tests/conversation-history.spec.ts --output /tmp/issue78-web-results
```

停止自己的 Web 后，用启动时保存的 `API_PID`、`MOCK_PID` 结束自己创建的进程，再在仓库根目录执行 `docker compose -f infra/issue78.persistence.compose.yaml stop`。卷保留用于重启验证；不要运行其他项目的 `down -v`。

## 正式入口与回退

- 服务端：`APP_HISTORY_ENABLED=false`、`APP_EVIDENCE_ENABLED=false`；Web：`NEXT_PUBLIC_APP_HISTORY_ENABLED=false`。Web 开关是构建变量，修改后需要重建。关闭后继续使用原 `stream.messages`，Reader 返回原结构，无业务 DB 初始化/查询。
- 开启前显式对**目标数据库**运行迁移。正式 Compose 透传两个服务端开关及 Web build arg，但本任务未改变或启动任何既有部署。
- API 与现有 Agent Protocol 共用 `DEMO_API_TOKEN` 和自定义认证；History sync 只收 `thread_id`，由服务端按协议回读 State，不接收客户端消息正文。
- `GET /app/history/threads/{id}/messages` 支持 `limit`、`cursor`、后续页的 `checkpoint`；当前分支变化返回 409，需重新从第一页加载。会话列表继续用已有 `threads.search`。
- `run_id` 仅在 Host 能取得时填写；无法确定归属的历史消息或其他 Reader 调用来源保留 NULL。Evidence 写入失败不重打 MCP，也不向 Repair/HITL 提供新授权。

## Phase 3：跨 Graph 复用

Phase 1/2 的历史 M0–M9 保留不变；Phase 3 唯一验收为 [P3-G0～G7](plans/issue-78-phase3-integration.md#6-phase-3-唯一权威-gate不得预填-pass)，实际结果见 [Phase 3 报告](issue78-phase3-validation.md)。不需要新的表、迁移、API 服务或前端 Hook。

| Graph ID | Aegra config | 模型/用途 |
| --- | --- | --- |
| `agent` | `aegra.issue78-demo.json` | 正式 Graph 的测试 FakeModel；包括 `/fake-slow`、`/fake-fail` |
| `deep_diagnosis` | `aegra.phase-b1.json` | Core Deep FakeModel Reader Smoke |
| `deep_diagnosis_planning` | `aegra.phase-b1.json` | Planning FakeModel + 本地 Todo |
| `deep_diagnosis_skills` | `aegra.phase-skills.json` | Skills V2 FakeModel + 只读 `read_file` |

在前文隔离 PG/迁移/Mock 的同一终端中，**启动 API 前**增加：

```bash
export DEEP_DIAGNOSIS_FAKE_MODEL=true DEEP_DIAGNOSIS_ENABLE_PROVIDER=false
export TRIAGE_MOCK_DATASET=memory-web
# 选定一个实验 Profile；B1 包含 Core Deep 和 Planning，Skills 应独立进程运行。
(cd server && uv run --frozen aegra serve --config aegra.phase-skills.json --host 127.0.0.1 --port 12079)
# 另一终端使用相同的测试环境；Graph ID 与选定 Profile 对应。
(cd apps/web && NEXT_PUBLIC_API_URL=http://127.0.0.1:12079 NEXT_PUBLIC_ASSISTANT_ID=deep_diagnosis_skills NEXT_PUBLIC_DEEP_DEMO=true NEXT_PUBLIC_APP_HISTORY_ENABLED=true pnpm dev --hostname 127.0.0.1 --port 13078)
```

不要与前文 API 同时占用同一端口。切换 B1/Skills 时先终止自己刚启动的 API；不要杀死占用端口的未知进程。端口占用时选择新的本机端口并同步修改数据库 URL、Web API URL 和协议测试 URL（测试允许 API `12079` / `12089`）。本次使用 PG `15488`、API `12089`、Web `13088`，避开已有 Demo。实验 Profile 复用 Aegra 默认 CORS；正式 Fake Profile 的 Web origin 是 `13078`。

也可以在无 dotenv 的独立工作树直接运行现有 Skills 启动器：

```bash
python3 scripts/skills_demo.py --persistence --api-port 12089 --web-port 13088 --db-port 15489
```

`--persistence` 显式对**本次新建的独立 PG**执行原迁移，打开服务端两个开关和 Web 开关；不传则仍默认关闭。该启动器的临时容器随 Ctrl-C 清理，不用于重启留存验证；需要保留卷时使用前文独立 Compose。API Key 是该启动器公开的本地测试占位值，不使用正式凭据。启动器不继承真实 Provider、Trace 或数据库配置。

### Phase 3 人工检查清单（当前 NOT RUN）

必须由真人实际操作并记录，AO/Playwright 结果不替代：

1. 正式 Fake Profile 执行前文两轮、刷新、侧栏切 Thread、SSE 重连、失败 Run 和可用父 checkpoint 的重新生成。重生成后显示当前分支；旧 Assistant 版本仍保留在业务表。History 独有消息没有 SDK 父 checkpoint 时不能执行重新生成/编辑。
2. B1 选择 `deep_diagnosis_planning`，发送合成问题两轮，检查 Todo/Reader Timeline 与同步提示。另建 Core Deep Thread 做 Reader Smoke。
3. Skills **新建 Thread** 发送 `CrashLoopBackOff`，看到一次 `read_file` 和四个 Reader；`read_file` 没有 `evidence_id`，四 Reader 的 ID 可用原 Evidence API 回查，来源 Graph/Thread/Tool Call 正确。同 Thread 发送“上轮结论是什么”，再刷新，应只有四条可见聊天、四份 Reader Evidence。
4. 用“新 Skills Thread”/原“New thread”/侧栏切换并检查不串消息；按钮异常要记录，不能只凭一次 click 成功就算 PASS。也可显式打开不含 `threadId` 的 URL 作隔离对照，但不能冒充按钮测试。
5. Skills 新 Thread 发送“你好”，不读取正文/Reader；完成 Run 后可普通多轮。**不测试/承诺旧 pin 中间节点 Checkpoint Resume**。
6. 记录操作者、日期、浏览器版本、Graph/Thread、步骤结果、是否重复泡泡及脱敏证据。未执行保持 `NOT RUN`；未确认保持 `UNKNOWN`。不得截图 Key/真实日志。

### 增量自动验证

服务端在独立 PG 环境下运行：

```bash
cd server
ISSUE78_TEST_DATABASE_URL="$DATABASE_URL" uv run --frozen pytest -q tests/test_phase3_persistence.py tests/test_phase3_agent_pg.py
# 正式 Fake Profile 运行时：
ISSUE78_TEST_API_URL=http://127.0.0.1:12079 uv run --frozen pytest -q tests/test_app_protocol.py
# B1 API 运行时；仅测试该 Profile 的图，Skills 项明确 skip：
ISSUE78_PHASE3_PROFILE=b1 ISSUE78_TEST_API_URL=http://127.0.0.1:12079 uv run --frozen pytest -q tests/test_phase3_protocol.py
# 停止本次 B1 API、启动 Skills API 后：
ISSUE78_PHASE3_PROFILE=skills ISSUE78_TEST_API_URL=http://127.0.0.1:12079 uv run --frozen pytest -q tests/test_phase3_protocol.py
```

实验协议测试的 `DATABASE_URL` 必须与 API 指向同一个**隔离测试库**，测试进程也需要本次 `DEMO_API_TOKEN`。CI 的 persistence job 顺序启动三个 Profile，skills job 继续验证开关 OFF。

## 留存、备份与手工维护

- `app_evidence` 只保存应用收到的受限 MCP 快照（包括失败回执），不代表全量日志；日志可能包含敏感内容。`app_conversation_messages` 保存可见 History 与旧分支版本，`app_conversations` 保存 Thread 索引。
- **无 TTL、无定时清理**：默认随 PostgreSQL 卷持续保留，直至管理员显式删除。旧版本也增长存储量；分页/摘要只改变展示或送模视图，不删除底层数据。
- Aegra Checkpoint/interrupt、Incident Memory（含撤销标记）、业务 History/Evidence、Trace 分别管理。清理任何一层不意味着其他层被级联删除；撤销 Memory 不删除历史聊天/Reader 快照，Reviewer S1 的本轮签记也不是 DB 生命周期。
- 备份前核对目标库/Host/端口、容器标签和卷归属。只在本机受限目录保存备份，避免将含日志/聊天的导出提交或上传。恢复到新的隔离库，先核对版本、显式复跑业务迁移，再验证原 ID 与 Checkpoint；恢复旧 Evidence 不赋予 Reviewer 或 Repair 新授权。

先做只读核对（不显示数据库 URL/密码，不输出 payload）：

```sql
SELECT current_database(), current_user, inet_server_port(), version();
SELECT count(*), min(observed_at), max(observed_at) FROM app_evidence;
SELECT graph_id, count(*) FROM app_conversations GROUP BY graph_id;
SELECT active, count(*) FROM app_conversation_messages GROUP BY active;
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables WHERE relname LIKE 'app_%';
```

需要删除时另行明确批准**隔离测试库**、Thread/日期范围及备份方案；确认后在维护窗口手动操作，复核业务表间关系和独立 Checkpoint/Memory 的残留。不提供自动 DELETE、TRUNCATE、定时任务或默认 `down -v`。本次实测只有独立容器 stop/start，未清空任何业务数据或稳定卷。

回退仍只需关闭三个开关并重建 Web/重启对应 API；不删表、不替换 Checkpointer，不重放 MCP 以补归档。停实验 Profile 后正式入口按原配置运行。History/Evidence DB 故障有显式 503/`evidence_persisted=false`；若同一 PG 完全不可用，Aegra 自身 Checkpoint 也会受影响，不承诺无数据库仍能运行整个 Agent Server。
