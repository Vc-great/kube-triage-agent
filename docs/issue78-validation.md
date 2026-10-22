# Issue #78：Implementation 验证记录

本报告对应 [唯一设计 M0–M9](plans/issue-78-conversation-evidence-demo.md)，不是新的验收标准。实施基线为 2026-10-22 `origin/main=6247925d124465485eeff94754a2205c8fd81d02`，Planning PR #79 已合并；#77 也已合并且仅修改 Skills 计划，无运行时代码冲突。实施分支 `ao/evidence-history-web/implementation`，独立 AO Worktree。

## 环境与实测

macOS arm64；Python 3.14.6；仓库 frozen lock：Aegra API/CLI 0.10.8、Deep Agents 0.7.28、LangGraph SDK 0.4.6、psycopg 3.3.6；Web Node 24.20.0、Next.js 16.3.8、SDK 1.12.0、pnpm 10.5.1。依赖从本机缓存离线复用，未升级版本。

独立 PG18 镜像 `pgvector/pgvector:0.8.7-pg18-bookworm`，仅 loopback `15478`，本任务容器 `kta-issue78-pg` 带 AO session 标签；独立卷 `kta-issue78-pg`。运行现有 Mock MCP（8000）、同一 Aegra 服务（12079）和 Web（13078）。最初 Docker Desktop 未启动，复用已安装运行时及已有镜像后验证；未操作其他项目容器、卷、端口或真实集群。

| Gate | 状态 | 实际证据与限制 |
| --- | --- | --- |
| M0 | PASS | Host `git fetch origin`；#79/#77 合并状态核对；独立 Worktree、独立 PG 容器/卷/端口。最初 Smoke 用 `docker run`；随 PR 提供等效独立 Compose。 |
| M1 | PASS | Aegra 0.10.8 `http.app` + `enable_custom_route_auth=true`，认证自定义路由以 `httpx.ASGITransport` 回读同一 app 的真实 PG Thread State；合成消息 ID 与 checkpoint 实测，未读取内部表或新增 Agent Server。 |
| M2 | PASS | `test_app_persistence.py`：真实 Reader 执行路径 + 合成成功/403/404/Timeout；SQL 和 GET 回查、tool_call_id、状态和 payload 摘要对应；真实 HTTP FakeModel→Mock MCP 两轮闭环。 |
| M3 | PASS | 合成长结果保留既有 16384 字符加截断后缀语义（非 UTF-8 字节限额），8s/四工具/参数策略未改变。实际停止本任务 PG 时 Mock MCP 只执行一次，Reader 仍成功、`evidence_persisted=false`；无无限重试。 |
| M4 | PASS | 独立 PG 10 轮同文本不同 ID；重复 sync 零新增；稳定行 sequence、当前分支 position、分页、同 ID 不同内容留旧版本。真实 HTTP 两轮与 re-entry 查询一致。 |
| M5 | NOT RUN（真人） | AO Browser 已自动执行两轮、Tool/Evidence 展示及 History 同步。真人手工操作尚未执行；按设计不把自动化等同真人 Gate。完整复现步骤见 [Demo](issue78-demo.md)。 |
| M6 | PASS（Mock） | 3 项真实协议测试通过：两轮 SSE；fail/cancel/checkpoint regenerate；原生 interrupt_before→携原 checkpoint Resume、SSE join 重连。静态暂停虽 Run=success 但 State.next 非空时仍标 interrupted；失败 Run 保留 failed。History 不把半截输出标完成，旧完成轮不降级。 |
| M7 | PASS（Mock） | 后端全量 867 PASS / 3 SKIP（协议测试需启动 API 后单独执行，3 PASS）；双开关开启时 Mock Repair/HITL/Memory/Deep 定向 96 PASS。Aegra checkpoint 重生成和原生 interrupt/Resume 通过。真实 K8s 写入 NOT RUN。 |
| M8 | PASS | 双开关默认关闭、原 Reader response 不变且不连接业务 DB；幂等迁移两次；本任务 PG stop/start 后原四条 History 和 Evidence ID 仍可查询。 |
| M9 | 本地 PASS，CI 待运行 | Ruff 通过；Web lint 0 error、18 个既有 warning；生产 `pnpm build`/TypeScript 通过；前端合并/动作 5 PASS；`git diff --check` 通过。PR/CI 与最终复核见后续补记。 |

命令：

```text
server/: uv run --frozen ruff check src tests
server/: ISSUE78_TEST_DATABASE_URL=<isolated-db> uv run --frozen pytest -q
  初次 867 passed in 225.69s；后续完整回归 867 passed, 3 skipped in 149.33s。
server/: APP_HISTORY_ENABLED=true APP_EVIDENCE_ENABLED=true uv run --frozen pytest -q
  tests/test_phase3b.py tests/test_incident_memory.py
  tests/test_incident_memory_phase34.py tests/test_deep_diagnosis_phase_a.py
  96 passed
server/: ISSUE78_TEST_API_URL=http://127.0.0.1:12079 DEMO_API_TOKEN=<local-test-key>
  uv run --frozen pytest -q tests/test_app_protocol.py
  最终 3 passed in 12.81s。cancel 使用 0.10.8 的 wait=1；Resume 携 checkpoint。
apps/web/: pnpm lint
apps/web/: NEXT_PUBLIC_APP_HISTORY_ENABLED=true pnpm build
apps/web/: pnpm exec playwright test tests/conversation-history.spec.ts --output <tmp-dir>
  最终 5 passed（含History独有消息的动作渲染断言）
git diff --check
```

## 失败、偏差与剩余限制

- 首次 `aegra serve` 没有显式 `--config` 而失败，修正后 M1 实测通过。仅空 Thread 没有 Graph metadata 时 State 为空，未当作有效历史。
- 生命周期实测发现静态 interrupt 的 Run 可为 success，而失败 Run 也可能有 State.next。已按失败/取消→暂停→完成的优先级分类，补入 SQL/协议回归；Resume 的 input=null 必须携 checkpoint（否则 0.10.8 返回 422），未修改 Aegra/审批来绕过协议。
- 首次 sandbox build 无法取 Google Inter；一次后续构建命中 sandbox 的 Turbopack 绑定端口失败缓存。停止本任务 dev、清理生成缓存后 Host 构建暴露 Hook 类型推断问题；修正后编译、TypeScript、产物生成全部通过。既有字体下载依赖、Tailwind module-format warning 未做无关改造。
- 浏览器测试曾与本任务 API 重启重叠，观察到明确的历史降级提示和连接拒绝；未把那次请求标为保存成功。恢复后服务端可补同步。浏览器错误缓存中的历史连接拒绝不代表后续请求仍失败。
- 同应用 ASGITransport 是 S0 实测后的受控协议适配：无网络自请求死锁、无外部 Token、沿用原认证；不开第二服务。自定义路由对外与原 API 使用同一认证。
- Evidence 为一次实际调用一行，不承诺跨进程 exactly-once；不会因归档失败重打 Reader。历史版本按 `(thread_id, source_message_id, content_sha256)` 保留，当前分支投影不会覆盖旧正文。
- 早于首次同步且已丢失的流式 chunk 无法凭空恢复；只能保存 Aegra State 实际持有的内容。无法确认完成的 Assistant 保守标 partial。旧 Thread 不做批量迁移，空记录标 legacy。
- 首轮 AO 审阅要求修复 History 独有 Assistant 的重新生成入口：已改为仅有 SDK 的有效父 checkpoint 才显示动作，提交处也拒绝缺失 checkpoint；不会把数据库消息当成新的执行输入。
- CI 增加独立 `persistence` job，使用 PG18 + FakeModel/Mock MCP 实际运行全部 11 项 SQL/协议测试；Web job 纳入 5 项合并/动作测试。初次 CI [run 39767676411](https://github.com/Vc-great/kube-triage-agent/actions/runs/39767676411) 的 Python/Web/Compose 全部通过，后续 head 结果以 [PR #81](https://github.com/Vc-great/kube-triage-agent/pull/81) 检查区为准。History 独有 Human 同样隐藏缺少 SDK 状态快照的编辑入口。
- 未做攻击测试、真实 Kubernetes 写入、RBAC 修改、付费模型调用或敏感日志外传。没有将 Mock 成功解释为真实 Repair 或集群验收，也不关闭 #78。
