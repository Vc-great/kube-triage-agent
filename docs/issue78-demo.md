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
