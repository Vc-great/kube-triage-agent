# Phase 0 实测记录（2026-10-10，Asia/Shanghai）

本页只记录当前 Mac 工作环境的实际执行；未 SSH 到 dev01，也未接入 Kubernetes、LLM 或 MCP。`.env` 由随机密码生成且未输出内容。

## 1. 只读基线

| 命令 | 实际结果 |
|---|---|
| `git status --short --branch; git remote -v` | detached HEAD、仅初始 LICENSE、无工作区改动；origin 为 `Vc-great/kube-triage-agent` |
| `docker --version; docker compose version` | Docker CLI 29.4.0、Compose v5.4.0 |
| 沙箱 `docker info` | Docker socket 权限被拒；不能代表 Host Docker 不可用 |
| Host `docker info --format '{{.ServerVersion}}'; docker compose ls --format json` | Engine 29.7.2；此前仅 `ragflow-lab running(5)` |
| Host `docker ps --format '{{.ID}} {{.Names}} {{.Status}}'` | 原有 5 个 `ragflow-lab` 容器 ID：`ec91a583a0c0`、`9fa3d95bac3a`、`7c09066f7eb6`、`8d31201680ff`、`f119a6b94aa5` |
| `lsof -nP -iTCP:12026 -sTCP:LISTEN` 与 13000 同式 | 两端口均无监听 |
| `uv python list --only-installed; node --version; corepack pnpm --version` | 已有 Python 3.13.14、Node 24.20.0、pnpm 10.33.0；容器使用另行固定版本 |

## 2. 构建、启动和 API 验收

| 命令 / 检查 | 结果 |
|---|---|
| `git switch -c codex/phase0-infrastructure` | PASS；本任务独立分支 |
| `git ls-remote` 上游两个仓库、PyPI JSON 只读查询 | PASS；Agent Chat UI `28cfb43…`，Aegra CLI/API `0.10.8` |
| `uv lock --python 3.13`（`server/`） | PASS；锁定 Aegra 0.10.8、LangGraph 1.2.14、Python SDK 0.4.6 |
| `python3 scripts/check-ports.py` | PASS；启动前两端口空闲；运行后正确识别为本项目持有 |
| `./scripts/compose.sh config --quiet` | PASS；无密码输出 |
| `python3 -m json.tool server/aegra.json` 与 `python3 -m compileall -q server/src scripts` | PASS |
| `./scripts/compose.sh up -d --build --wait` | PASS；四个项目容器均 healthy |
| `python3 scripts/acceptance.py` | PASS × 2（最终代码修复后重跑）；逐项结果见下表 |
| `make check`（最终内容块验收脚本） | PASS；静态 Compose 校验与全部 API 项均通过 |

自动验收脚本实际发起 Thread/Run/Stream API 请求，使用固定项目名脚本 `restart api`，随后重新查询同一 Thread。

| 能力 | 结果 |
|---|---|
| `GET /health` | PASS |
| `agent` Graph 可查 | PASS |
| Thread 创建 | PASS |
| Run 与 SSE 事件 | PASS |
| `get_demo_cluster_status` tool call/result，`mock=true` | PASS |
| 同 Thread 两轮对话与 history | PASS |
| `interrupt()` 待审批 | PASS |
| 结构化恢复：approve、reject | PASS / PASS |
| 仅重启本项目 API 后 health、状态和 history | PASS / PASS / PASS |

## 3. Web UI

使用 `playwright` CLI 在 `http://localhost:13000` 真实浏览器执行 `open`、`snapshot`、`fill`、`click`、`requests`、`response-headers`。网页标题为 Agent Chat；访问 `localhost:12026` 的 `/info`、`/threads`、`/runs/stream` 均 200。`/runs/stream` 响应 `content-type: text/event-stream`、`access-control-allow-origin: http://localhost:13000`。

| 浏览器操作 | 结果 |
|---|---|
| 输入 `status` 并发送 | PASS；显示 tool call `get_demo_cluster_status`、Tool Result 表格 `mock=true`、最终模拟消息 |
| 输入 `/approve-demo` | PASS；显示待审批卡片及 `Approve mock` / `Reject mock` |
| 点击 `Approve mock` | PASS；显示 `Simulated approval approved` |
| 再次触发并点击 `Reject mock` | PASS；显示 `Simulated approval rejected` |
| 流式传输 | PASS；浏览器请求与 SSE 响应已观察，消息通过 UI 更新；确定性 Graph 很快，未测量逐 token 动画 |

发现并修复：上游 UI 发送的是 text content block 数组，初版 Graph 的 `/approve-demo` 路由只识别字符串，页面最初显示 echo。Graph 已归一化文本块，新增审批提示消息和专用结构化审批按钮；重建后以上 UI 操作通过。上游 Next.js 构建仍对 `tailwind.config.js` CommonJS/ESM 格式给出警告，但构建、页面与交互通过。上游 API passthrough 发出认证方式提示；本项目本地验收走浏览器直连 Aegra，不把此路径用于公网。

## 4. 隔离复核

| 只读命令 | 实际结果 |
|---|---|
| `./scripts/compose.sh ps --format json` | 仅 `api`、`postgres`、`redis`、`web`，全为 healthy，`Project=kube-triage-agent` |
| 同一输出的 `Publishers` | API `127.0.0.1:12026`；Web `127.0.0.1:13000`；Postgres/Redis `PublishedPort=0` |
| `docker volume inspect ... --format '{{.Name}} {{index .Labels "com.docker.compose.project"}}'` | `kube-triage-agent_postgres_data`、`kube-triage-agent_redis_data` 标签均为 `kube-triage-agent` |
| `docker network inspect kube-triage-agent_private ...` | 同一项目 label |
| `docker inspect kube-triage-agent-postgres-1 --format '{{range .Mounts}}{{.Name}} {{.Destination}}{{end}}'` | `kube-triage-agent_postgres_data /var/lib/postgresql`，符合 PostgreSQL 18 挂载要求 |
| 验收后 `docker ps --filter label=com.docker.compose.project=ragflow-lab` | 原有 5 个容器 ID 未变，仍为 `Up 3 days`；`docker compose ls` 中仍 `ragflow-lab running(5)` |

## 5. 未运行与边界

- **NOT RUN**：dev01 SSH 或部署；用户未指示远程修改。
- **NOT RUN**：真实 Kubernetes/MCP/LLM 路径；本阶段明确排除。
- **NOT RUN**：备份恢复演练与 `make reset`；不会为验收删除项目数据。
- **NOT RUN**：公网入口或真实认证模式；当前 `AUTH_TYPE=noop` 只允许本地隔离验收。
- **未固定**：Compose 镜像多架构 registry digest；使用具体版本 tag，可按部署架构补 digest 后再次验证。
