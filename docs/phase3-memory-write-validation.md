# Phase 3-1 Incident Memory Write + Review 验证记录

> 2026-10-15。结论：**DEMO_WORKFLOW_ONLY**，仅用于私有单用户 Demo。同一 Demo API Key 持有人可以自行发起 Run 并提交 `approve` Resume；这里的审阅是工作流确认，不是独立真人身份授权。真人 UI 点击未由 Codex 执行。

## BASELINE

- 执行 `git fetch origin main` 后，实时 `origin/main` 为 `8e295ffb1f7bb9d113f1319c681ad5e5a3ffabc4`。GitHub Connector 复核 PR #31 为 merged，merge SHA 与此一致。
- 独立 Worktree：`.local/worktrees/phase3-1-incident-memory-write`；分支：`codex/phase3-1-incident-memory-write`。主工作树原有未跟踪 `apps/web/AGENTS.md` 和 `apps/web/CLAUDE.md` 未触碰。没有从 Phase 3-0 Worktree 派生。
- `server/uv.lock` 与本机既有虚拟环境一致：`aegra-cli==0.10.8`、`langgraph==1.2.14`、`langgraph-sdk==0.4.6`。未升级 Python 依赖。Web 使用既有 pnpm 依赖的本地副本，无包下载。
- 阅读了 `docs/phase3-memory-compatibility.md`、Phase 3-0 spike、正式 `graph.py`/`auth.py`/`config.py`/上下文 Gate/Repair/MCP、Web 中断分发和现有测试。原第三阶段设计评审文档仍未在本 Worktree 找到；本次按用户给定的验收文本实施。

## IMPLEMENTATION

- `INCIDENT_MEMORY_ENABLED=false`、`INCIDENT_MEMORY_WRITE_ENABLED=false` 默认关闭；两项必须都精确为 `true` 才开启。非法布尔值拒绝启动。开启时另需服务端专用 `INCIDENT_MEMORY_PROVENANCE_SECRET`（32–256 个 ASCII 字符，须与 Demo API Key 不同），缺失即启动失败。
- 正式 `auth.py` 在写功能开启时对**所有 HTTP Store PUT/DELETE** 返回 403；GET、search、namespace 列举保留原认证/读取行为。关闭时 HTTP Store 写行为与旧版一致。Graph 的 `Runtime.store` 写入不经过这两个 HTTP hook。
- 普通诊断的 `tools` 节点对真实执行的 `pods_get` 回执生成 HMAC 证明，绑定 Thread、诊断 Human/AI/Tool ID、调用参数、工具状态及响应摘要。候选仅接受紧邻命令前最后一轮完整诊断中按顺序配对的一个成功 `pods_get`；客户端伪造的历史 AI/ToolMessage 因无服务端证明被拒绝。签名只用服务端独立密钥；签名状态不进入 Store 值。
- 候选从可解析 Pod YAML/JSON 投影有限字段。Kubernetes Namespace 固定为 `kube-triage-demo`，Pod name/UID/症状需与可信调用及响应匹配；根因、未证实 Workload、无可信观测时间保持 `null`。不复制模型报告、原始 ToolMessage、日志、环境变量、标签或注解。Store namespace 固定为 `("kube-triage", auth identity, "incidents", "v1")`，身份只从 Aegra `get_auth_ctx().user.identity` 取得且仅接受 `demo-user`。这是 Aegra 0.10.8 内部 API，升级须重验。
- 精确 `/remember-incident` 与 `/forget-incident <32 位小写十六进制 ID>` 分别进入独立 Review/Commit 和 Revoke Review/Commit；`/repair-demo` 原路径独立。Memory Resume 严格比对 kind、ID、hash、schema_version、decision、当前 Thread 与服务端身份。批准快照和时间戳进入 Checkpoint 后才写 Store；固定 key 的 `aget→aput→aget` 返回 `stored`、`already_committed`、`conflict` 或 `unknown`。撤销改为 `revoked`，不删除记录；重复撤销返回 `already_revoked`。
- Web `ai.tsx` 分发两个新 kind 到独立审阅卡；显示安全投影、历史性质及 `DEMO_WORKFLOW_ONLY`。使用实际 SDK `command.resume` 形状，加载时禁用重复点击；不做编辑、检索、列表或自动修复。
- 隔离真实 Aegra 使用 `scripts/spikes/phase3_memory/phase31_product_mock.py` 包装**正式产品 Graph**，将 LLM、四 Reader 和 Repair transport 全部替换为 Fake/Mock；`aegra-phase31-product.json` 仍加载正式 `auth.py`。`phase31_live_probe.py` 保存脱敏的 SDK/HTTP 结果，不接真实模型、MCP 或 Kubernetes。

## 隔离与安全证据

- 测试前只读枚举既有 Compose 项目、容器、卷和 `127.0.0.1:15441/18041`。仅创建 `kube-triage-phase31-20261015` 项目、专用 PostgreSQL 卷与 DB，Aegra 仅绑定 `127.0.0.1:18041`。随机 Demo Key、DB 密码、来源 HMAC 密钥在实验期间保存在 gitignored `.local/phase31/env`，权限 `0600`；实验结束后已删除该密钥文件。未碰现有 `.env`、Compose 项目、真实 K8s/MCP/LLM。日志扫描确认三种密钥均未出现在日志中。
- 首次正式 Aegra 检测发现：客户端可提交伪造 AI/ToolMessage 历史并获得 Memory 中断。修复后服务端 `pods_get` HMAC 回执成为候选前置条件；同一伪造输入实测 `interrupt=null`、`memory_status=rejected`、Store 0 写。保留此失败与修复经过，不能把初次结果算 PASS。
- 最终 HTTP 矩阵：无 Key/坏 Key 的 PUT/覆盖/DELETE/GET/search/namespace 均 401；有效 Demo Key 的 PUT 新建/覆盖/DELETE 均 403，GET 不存在为 404，search/namespace 为 200；伪造 `users/demo-user` 前缀、`other` owner、畸形 namespace 写入均 403。Graph 正常保存后，直接对该 key 的 HTTP PUT/DELETE 均 403；随后 Graph 撤销预检读到原活动记录并完成独立审批。`Runtime.store.aput` 返回 `stored`。
- 正式 Graph SSE `updates.__interrupt__` 的 Memory payload 键为 `kind/candidate_id/candidate_hash/schema_version/preview/options/notice`；撤销 payload 键为 `kind/memory_id/record_hash/schema_version/options/notice`。SDK Resume Reject=`rejected`、Approve=`stored`、重复 Resume=`BadRequestError`；Memory Resume 发给 Repair 中断得到 `repair_status=rejected`，无 Mock Scale；独立合法 Repair Resume 得到模拟 `repair_status=finished`、`simulated=true`。
- 用新 Thread 保存案例，**仅重启 Aegra** 后在另一新 Thread 发起该 ID 的撤销预检，得到 `incident_memory_revoke_review`，随后 Reject 保持活动；PostgreSQL 只读查询 `prefix=kube-triage.demo-user.incidents.v1` 的该 key 为 `active|demo-user|kube-triage-demo`。这证明当前隔离拓扑内跨 Thread 与重启持久化，不证明多实例或生产 Redis 重连。
- 清理前核验容器与卷的 `com.docker.compose.project=kube-triage-phase31-20261015` 标签；只对该项目执行 `docker compose ... down -v`。清理后专用项目、卷与两个监听端口均不存在，其他项目未操作。

## GATES

| Gate | 状态 | 级别、请求/断言与复现证据 |
| --- | --- | --- |
| G31-00 | PASS | 实时 Git/本机：上述 SHA、PR #31 合并、独立 Worktree、锁与安装版本。 |
| G31-01 | PASS | Fake/pytest：默认关闭和单开关关闭时 Memory Store 0 I/O；旧普通诊断/Repair/Gate A/B 在全量回归中通过。`PYTHONPATH=server/src .../pytest -q server/tests`。 |
| G31-02 | PASS | 25 项新增 Fake/InMemoryStore 测试的一部分：Pod 投影、owner/Namespace、脱敏、根因和 Workload `null`；服务端字段白名单与 UTC 时间校验。 |
| G31-03 | PASS | Fake ToolMessage 的 namespace/name/status/ok/YAML/缺完成回复/旧轮/配对负例；真实 Aegra `forged_history` 一次无证明注入被拒绝，真实 Mock Reader 回执可进入 Review。 |
| G31-04 | PASS | pytest 精确命令路由；正式 Graph 真实 Aegra 的普通诊断→Memory、独立 Repair 两种中断。 |
| G31-05 | PASS | MemorySaver/InMemoryStore：6 类 Reject/错字段负例、跨 Thread 错候选；真实 Aegra SDK Reject、Approve、重复 Resume 拒绝。 |
| G31-06 | PASS | InMemoryStore：固定 key 重试=`already_committed`、不同值=`conflict`、丢回执=`unknown`；竞态测试明确观察到两次写尝试，**不宣称 exactly-once**。 |
| G31-07 | PASS | 正式 `auth.py` + 真实隔离 Aegra/PostgreSQL：上述 HTTP 401/403/200/404 矩阵与 Graph 内 `stored`。`.local/phase31/product-results.json`。 |
| G31-08 | PASS | 正式产品 Graph + FakeModel/Mock Reader + 真实 Aegra/PostgreSQL/SDK：两种中断同服务、SSE/Resume、跨 Thread/重启、DB 只读查询。`.local/phase31/restart-result.json`。 |
| G31-09 | PASS（负面证明） | 同一个有效 Demo Key 完成诊断 Run 与合法 Approve Resume；这证明**没有独立真人授权保证**。 |
| G31-10 | PASS | Fake + Aegra：按 ID 撤销需独立确认；Reject 不写，Approve 后 `revoked`，再次命令 `already_revoked`；跨 owner/哈希不符拒绝。 |
| G31-11 | PASS | 全量 Python 回归 295 passed；Memory Resume→Repair 拒绝，原四 Reader、工具预算和 Gate A/B 测试通过。 |
| G31-12 | PASS | `pnpm exec tsc --noEmit`、`pnpm lint`（0 error、18 条既有 warning）、Prettier check、`pnpm exec next build --webpack` 成功；SSE payload 键与卡组件类型匹配。默认 Turbopack build 因执行环境端口绑定限制失败，不能冒充其通过。 |
| G31-13 | NOT RUN | 真人在浏览器点击 Approve/Reject/撤销须由用户本人完成；见 Demo 手册。 |
| G31-14 | PASS（本地）/ CI 待确认 | `pytest`: 295 passed；`ruff check`: all passed；`git diff --check`: 通过。Draft PR 与 CI 在创建后补记；此前历史的 270 passed 不计入。 |

## 残余风险与 Phase 3-2 Gate

- 本阶段仅为**私有单用户 Demo 工作流**。API Key 持有人可发起真实 Reader Run 并自行 Approve，且可通过 Aegra API 操作自身 Thread/Checkpoint。HMAC 阻止无服务端 Reader 回执的任意内容伪造，但不能提供独立 reviewer 身份、阻止合法回执重放或抵御掌握服务端密钥的人。若要求不可绕过的真人审核，Phase 3-2 为 **NO_GO**，需先设计独立 reviewer 与存储权限。
- `aget→aput` 不是事务 CAS，竞态下可能双写或最后写覆盖；Demo 阶段只给 `unknown/conflict` 有界回执。撤销与并发新写之间也无数据库级锁，Phase 3-2 读取必须过滤 `status!=active`。
- Store 投影不会擦除早已写入的 Thread History/Checkpoint 中原始 ToolMessage；新增候选与 HMAC 元数据自身不含原始日志/密钥。撤销也不清除旧 Checkpoint。语义检索、Top-K、当前 UID 对比、Prompt 注入、真实模型 A/B、复杂编辑均未实现。
- **PHASE_3_2_GATE：CONDITIONAL_READY**，条件为用户真人 UI 验收、Draft PR CI 结果确认，并继续沿用 `DEMO_WORKFLOW_ONLY` 风险模型。此报告不启动 Phase 3-2。
