# Phase 1A 实测记录（2026-10-11，Asia/Shanghai）

基线：`git fetch origin` 后 `origin/main=28a920b5a98c6ae642ec6408c53c9c14de32cce1`。本机只操作 Compose 项目 `kube-triage-agent`；未接 Kubernetes、LLM 或 dev01。`.env` 未提交或打印。Playwright CLI 曾回显首次输入的 Key，已立即将本项目 Key 轮换，并用旧浏览器会话验证被拒绝、要求重输；最终 Key 未输出。

## 验收矩阵

| ID | 状态 | 实际命令与关键证据 |
|---|---|---|
| A1 Compose 隔离 | PASS | `./scripts/compose.sh ps --format json`：`api/mock-mcp/postgres/redis/web` 五服务均为 `Project=kube-triage-agent`；MCP/DB/Redis `PublishedPort=0`，Web/API 仅 `127.0.0.1`。`docker ps --filter label=com.docker.compose.project=ragflow-lab` 的五个原有 ID 前后相同。 |
| A2 正确 Key | PASS | `python3 scripts/acceptance.py`：Thread 创建、Run/SSE、State/History 与 Resume 通过。 |
| A3 无/错 Key | PASS | 同上：匿名 Assistant、Thread、State、History、Run、SSE，以及匿名/错误 Key Resume 均 401；错误 Key Thread/Run 401。 |
| A4 跨容器 MCP | PASS | 同上：`list_pods` 结果有 `mock=true`、`static-fixture`、`CrashLoopBackOff`；`./scripts/compose.sh logs mock-mcp --tail=120` 有来自 API 容器的多次 `POST /mcp HTTP/1.1`。 |
| A5 浏览器 UI | PASS | Playwright CLI 真实浏览器：Key 表单、`pods demo`、Tool 名/参数/展开的 Mock 结果、approve/reject 按钮与结果均可见。最终格式化结果为 `healthy-pod: Running, crashloop-pod: CrashLoopBackOff`。 |
| A6 Namespace | PASS | `python3 scripts/acceptance.py`：`pods default`、`pods kube-system` 返回 `Namespace denied`；单元测试同时覆盖 Server 校验。 |
| A7 MCP 不可用/超时 | PASS | 仅执行 `./scripts/compose.sh stop mock-mcp`，本机 Run 在约 0.43 秒内返回“Mock MCP 服务暂时不可用”；随即 `start mock-mcp` 恢复。单元测试以短超时模拟慢工具，验证 `error_type=timeout`。`events demo unknown-pod` 实测返回“Mock MCP 工具拒绝了参数”。 |
| A8 审批回归 | PASS | API 验收通过 `interrupt()`、approve/reject；浏览器分别显示 `Simulated approval approved/rejected`。 |
| A9 持久化 | PASS | 验收脚本只重启本项目 API，随后同一 Thread 的 State/History 仍可读。Worker 崩溃恢复 NOT RUN。 |
| A10 审计 | PASS | 验收脚本在重启前检查 API 日志：有 `outcome=success` 与 `outcome=rejected` 的 `mcp_tool_call`，且不含当前 Token；断连演练有 `error_type=connection`。 |
| A11 GitHub Actions | PASS | PR #2 的 [CI run 38096772392](https://github.com/Vc-great/kube-triage-agent/actions/runs/38096772392) 结论 `success`；`python`、`web`、`compose` 三个 Job 均通过。 |

## 按测试类型区分

| 类型 | 命令 | 结果 |
|---|---|---|
| Python 单元/静态 | `cd server && uv run --frozen ruff check src tests && uv run --frozen pytest -q` | PASS，ruff 无错误，13 passed。覆盖路由、白名单、参数、Server fixture、认证函数、结果解包、超时与错误类别。 |
| 前端静态/构建 | `cd apps/web && pnpm lint && pnpm build` | PASS；lint 为 0 error、18 warning（主要上游组件）；Next.js build 成功，仍有原上游 Tailwind 模块格式警告。 |
| Compose 静态 | `POSTGRES_USER=ci_user POSTGRES_DB=ci_db POSTGRES_PASSWORD=ci-placeholder-only DEMO_API_TOKEN=ci-placeholder-only docker compose -f infra/compose.yaml config --quiet` | PASS，无输出。 |
| API/SSE 自动化 | `python3 scripts/acceptance.py` | PASS，20 项均打印 PASS；检查 401、MCP、审批、重启持久化和审计。 |
| 真实浏览器 | Playwright CLI `open/snapshot/fill/click/reload` | PASS；看见 Tool Call 和结果、approve/reject、旧 Key 被要求重输、新 Key 可读 Thread。 |
| GitHub Actions | [PR #2 / run 38096772392](https://github.com/Vc-great/kube-triage-agent/actions/runs/38096772392) | PASS，远端 `python`、`web`、`compose` 三 Job 完成且结论 `success`。 |

## 边界与风险

- Mock MCP 数据完全静态，路由完全确定性；没有真实 LLM Function Calling 或 Kubernetes 查询。
- 只验证 API 重启后的 Checkpoint/History；未测 Worker 进程崩溃恢复、备份恢复或公网安全性。
- `/health`、`/info`、`/docs`、`/openapi.json` 实测匿名 200；业务路由 `/assistants/search`、`/threads` 匿名 401。浏览器以受保护的 Assistant 查询检测 Key。
- `mcp-client` 首次查询发现工具并缓存；服务断开时单次失败，不无限重试。日志只含元数据，不含日志正文；拒绝的 Namespace 统一记 `<denied>`。

**Phase 1B 准入：暂不连接实验 Kubernetes。** 本阶段已证明协议、鉴权、拒绝和故障路径，但还没有真实只读 ServiceAccount/RBAC、实验 Namespace 范围、真实 MCP Server 的数据边界验证及凭据轮换方案。接入前先在隔离实验集群完成这些条件，继续禁止写操作。
