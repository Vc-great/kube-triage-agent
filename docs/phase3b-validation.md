# Phase 3B 验收记录（2026-10-12）

## 环境与来源

本次分支从 `origin/main=66a6b22` 建立，PR #7 已在该提交中。上游证据为 `containers/kubernetes-mcp-server` **v0.0.67** 的 `pkg/toolsets/core/resources.go` 与 `pkg/kubernetes/resources.go`：工具名 `resources_scale`，参数为 `apiVersion/kind/name/namespace/scale?`，实际 `GET` 后 `UPDATE` `scale` 子资源，RBAC verbs 为 `get/update`。没有以较新 main 的实现推断旧镜像。依赖 Python 3.13.14、uv 0.11.21、pnpm 10.5.1、Docker 29.7.2、Compose v5.4.0；Node/前端依赖复用本机缓存。

**全部执行写请求仅针对 `mock-repair-mcp` 进程内存，`simulated=true`；没有连接、查询或写入真实 Kubernetes。** 模型路径本轮为 `LLM_ENABLED=false`，没有真实模型 Run；Phase 3A 的 `deepseek-flash` 结论只作历史背景。Aegra API、SSE、Thread、History 和网页是真实运行的隔离栈；MCP Repair executor 是 Mock。私有 `.local/phase3b.env` 与浏览器认证状态在验收后删除，Token 未记录。

## Gate A

| 项 | 状态 | 证据与范围 |
| --- | --- | --- |
| A01 | **PASS** | `cd server && uv run --frozen ruff check src tests` 无错误；`uv run --frozen pytest -q` **65 passed**。`cd apps/web && pnpm lint` 返回 0，有仓库原有 18 条 warning；`pnpm build` 返回 0。Mock 与 Real override 的 `docker compose ... config --quiet` 均通过。两份新 YAML 静态解析为 Deployment 及 SA/Role/RoleBinding。 |
| A02 | **PASS** | `REPAIR_ENABLED` 缺省为 false，单元测试断言 `/repair-demo` 在关闭时不查询 Repairer。隔离 Aegra 验收的旧 echo、Reader 四工具、`/approve-demo` interrupt/resume 全 PASS；原四工具和预算未改。真实 LLM 本轮未重跑。 |
| A03 | **PASS** | `python3 scripts/acceptance_phase3b.py`：真实 Aegra Thread/SSE 有 `repair_approval`，State `next` 挂起，Checkpoint 的 proposal_id 前后相同；网页显示 `kube-triage-demo/Deployment/triage-repair-demo：0→1` 和 `simulated=true`。 |
| A04 | **PASS** | Aegra API 与网页各自执行 Reject，State 为 `rejected`；审批节点不调用写工具。Mock API 重建后审计汇总仅有一次 `repair_scale_call`，对应本轮唯一 Approve。 |
| A05 | **PASS（模拟）** | Aegra API 正确 ID Approve 后 State `repair_result` 为 `simulated=true`、`observed_replicas=1`、`write_attempted=true`。代码测试固定 `resources_scale(apps/v1, Deployment, triage-repair-demo, kube-triage-demo, scale=1)` 且只调用一次。网页 Approve 后清楚报告 `scale=1` 与“Pod 尚未 Ready”，未宣称根因修复。 |
| A06 | **PASS（离线注入）** | 单元测试覆盖错 proposal_id、额外 Kind/Namespace/name/scale、未知 decision，均零写；Aegra API 实测跨 Thread ID 拒绝、无 API Key 返回 401。目标参数只在服务器端生成。 |
| A07 | **PASS（离线注入）** | 单元测试覆盖执行前副本 2/3、断连、超时、401/403、写已改变 Mock 状态但回执超时：无自动重试，回查虽为 1 仍归类“写结果未知/失败”。真实网络与真实 RBAC 故障未演练。 |
| A08 | **PASS（模拟）** | 待审批 Thread `6c11a0fa-…` 在独立 API 重启与网页刷新后仍显示相同 proposal_id `5bf53948…`，随后 Reject 成功。已完成 Thread `72ec0cdc-…` 重启后 History/结果仍在。对已完成 Thread 重发同一 Resume 返回 HTTP 400；未新增写调用。单元测试亦覆盖重放时目标已为 1 的 no-op。 |
| A09 | **PASS（模拟）** | Aegra SSE/History 及网页分别观察到审批卡、Reject、Approve、scale/Ready 分离结果。审计仅有 `repair_decision`、`repair_scale_call`、`repair_result` 的非敏感字段；API 重建后的汇总为 4/1/1，未见 `DEMO_API_TOKEN=`。网页可见证据来自 Playwright 实际页面快照，未保存含凭据的截图。 |
| A10 | **PASS** | 项目名 `kube-triage-phase3b-demo`，仅启动其 postgres/redis/api/web/mock-mcp/mock-repair-mcp，端口 12027/13001。开始和结束时稳定项目六个容器 ID 均为 `0071c534ba8f`、`86f20eff96de`、`f39cb62b7bdf`、`0448756ba411`、`eac83ce1df53`、`06d49306e2c3`；`ragflow-lab` 五个仍为 `ec91a583a0c0`、`9fa3d95bac3a`、`7c09066f7eb6`、`8d31201680ff`、`f119a6b94aa5`。仅对此项目执行 `down`，精确删除其两个具名卷；项目容器/卷已空。 |

本轮主要命令：`uv sync --frozen --offline --python 3.13`、`uv run --frozen pytest -q`、`pnpm install --offline --frozen-lockfile`、`pnpm lint`、`pnpm build`、`docker compose -p kube-triage-phase3b-demo --profile repair-mock --env-file .local/phase3b.env -f infra/compose.yaml up -d --build --wait ...`、`python3 scripts/acceptance_phase3b.py`。Compose 只用本轮独立 project；私有环境文件未提交。

## Gate B：真实集群

用户未对 `ssh k8s-m` 所指集群、两份清单、短期 Token 创建及最终真人网页 Approve 给出独立明确授权。因此 B01–B08 均为 **BLOCKED / NOT RUN**：未 SSH、未 apply、未创建 Repairer Token、未启动 Real Repair MCP、未发起真实 `resources_scale`。静态 YAML、Compose 和上游代码检查不能代替真实 RBAC allow/deny、tools/list、Pod Ready 或重启验收。真实 HITL Demo **尚未通过 Gate B**。

| 项 | 状态 | 尚需证据 |
| --- | --- | --- |
| B01 | **BLOCKED** | 真实集群身份、Namespace 与同名对象的只读核查。 |
| B02 | **BLOCKED** | 单独许可后仅应用两份清单，生成 0600 短期凭据。 |
| B03 | **BLOCKED** | Repairer 与 Reader SA 的实名 RBAC allow/deny。 |
| B04 | **BLOCKED** | Real Repair MCP 恰好一工具、Reader 四工具、模型只绑定四读工具的运行态证据。 |
| B05 | **BLOCKED** | 真实网页 Reject 后 scale 仍为 0。 |
| B06 | **BLOCKED** | 新 Thread 提案与用户本人 Approve 导致真实唯一一次 0→1。 |
| B07 | **BLOCKED** | 真实 scale、Pod Ready 和断连/越权结果。 |
| B08 | **BLOCKED** | 真实审批 Thread 的重启持久化与其他服务/资源无影响。 |

## 已知风险与 CI

GET→UPDATE 存在并发竞态，写回执丢失无法证明 exactly-once；同一目标出现别的写入来源时，回查为 1 也不能归功于本次请求。Repairer 凭据同时用于 API 的固定 Deployment 归属 GET 与 Repair MCP 的 scale GET/UPDATE，需按演练窗口短期使用。Pod 列表如果不可解析，Ready 为 unknown，不可当作就绪。`busybox:1.36.1` 沿用项目已有样例，但真实节点是否缓存该镜像未验证。Phase 3A 的 CrashLoop/OOM 因果 grounding 问题仍在。Draft PR #8 的首轮远程 [GitHub CI run 38206356860](https://github.com/Vc-great/kube-triage-agent/actions/runs/38206356860)：`compose`、`python`、`web` 均 PASS；后续提交应以 PR 最新 CI 状态为准。
