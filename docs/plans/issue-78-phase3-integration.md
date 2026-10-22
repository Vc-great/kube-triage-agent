# Issue #78 — Phase 3 增量整合：跨 Graph 的 History / Evidence 兼容与 Demo 收口

> - 关联：[Issue #78](https://github.com/Vc-great/kube-triage-agent/issues/78)；已合并 [Planning #79](https://github.com/Vc-great/kube-triage-agent/pull/79)、[Implementation #81](https://github.com/Vc-great/kube-triage-agent/pull/81)、[Skills V2 #83](https://github.com/Vc-great/kube-triage-agent/pull/83)。
> - 状态：**Proposed / Phase 3 纯文档 Planning PR**；该计划合并前未批准实施。Phase 1/2 的实际代码已合入 main，**不得重复实现**。
> - 规划基线：2026-10-22 `main=339e99a3193dc9c10ce4c56aee776cf02a40a620`；实施前必须重新 fetch 并审查后续 PR。
> - 唯一权威验收：**本文件第 6 节 P3-G0～P3-G7**，只针对本次 Phase 3。原 `issue-78-conversation-evidence-demo.md` 的 `M0–M9` 仅负责 Phase 1/2 历史设计与交付记录；不复制、不重新定义。
> - 用户目标：**Demo-first，快速补齐**；一个实施 PR、独立 Mock/PG 环境，取消攻击专项、多租户、分布式安全/持久化平台等范围。
> - 与 #72 关系：Evidence Reviewer 当前只有 S1 离线 PoC；本期做兼容验证，**不替代 #72 独立实施 Gate**。

## 1. 当前实现与已核实缺口

### 1.1 已完成（不可重复造轮子）

- [`server/src/kube_triage/app_storage.py`](../../server/src/kube_triage/app_storage.py) + [`migrations/001_app.sql`](../../server/src/kube_triage/migrations/001_app.sql)：单一 PostgreSQL 实例，独立 `app_evidence`、`app_conversations`、`app_conversation_messages`，业务开关默认关闭。
- [`server/src/kube_triage/mcp_client.py`](../../server/src/kube_triage/mcp_client.py)：真正执行四 Reader 后自动保存**已经被工具层裁剪的回执/错误**，`evidence_id` 可回查；归档异常不重打 MCP，错误路径明确 `evidence_persisted=false`。
- 正式 [`graph.py`](../../server/src/kube_triage/graph.py) 的 `_execute_tool` 使用 `reader_context(graph_id="agent",tool_call_id,run_id)` 并传入 `thread_id`。Aegra 内置 PostgreSQL Checkpointer 未被替换。
- [`app_routes.py`](../../server/src/kube_triage/app_routes.py) 将业务 History/Evidence API 附着在原 Aegra FastAPI；服务端通过 Agent Protocol 回读 State、幂等同步 History；`GET /app/evidence/{id}`、`GET /app/history/threads/{id}/messages` 可用。
- [`use-conversation-history.ts`](../../apps/web/src/hooks/use-conversation-history.ts) 使用业务 History + `useStream` 合并展示，支持分页、当前分支、恢复及失败降级。
- [`docs/issue78-validation.md`](../issue78-validation.md)：既有独立 PG18 + FakeModel/Mock MCP SQL/HTTP 协议、存储故障降级、HITL/Memory 回归。**M5 真人浏览器验收仍 NOT RUN**；历史报告中的 M9“CI 待执行”应以已合并 [#81](https://github.com/Vc-great/kube-triage-agent/pull/81) 的 CI 为准。
- [Skills V2 #83](https://github.com/Vc-great/kube-triage-agent/pull/83) 已提供独立可启动原生 SkillsMiddleware、`read_file` 与 Web Demo；旧 [#80](https://github.com/Vc-great/kube-triage-agent/pull/80) 已按用户要求 **Closed / Not merged**。

### 1.2 Phase 3 实际缺口

| 缺口 | 仓库依据 | 优先级 |
| --- | --- | --- |
| Deep/Planning/Skills Reader 的持久证据**来源关联不完整** | `deep_diagnosis._reader_tools()` 调 `call_tool` 时未传 thread_id；无正式 Graph 的 `reader_context`，因此业务 Evidence 可能有空 `thread_id/graph_id/tool_call_id/run_id` | P1 |
| 实验 Aegra Profiles 没挂业务 API | `server/aegra.phase-b1.json`、`server/aegra.phase-skills.json` 只有 graphs/auth，正式 `server/aegra.json` 才有 `http.app` | P1 |
| 缺少新旧组件**联合实测** | #81 证明正式 Graph 的 M0～M9 Mock Gate，#83 证明 Skills 独立 Mock Gate；没有证据表明业务开关同时打开时实验 Graph 的业务 History/Evidence、Summary、Memory、HITL、SSE 都通过 | P1 |
| Reviewer 还未消费 DB Evidence | `deep_diagnosis_review.py` 是独立 #72 S1 PoC，以本轮执行 `ContextVar` 与 HMAC 对 Reader ToolMessage 做签记；目前没有 `app_storage` 使用 | P2：本期仅兼容，不直接整合 |
| 数据保留规则尚无执行级说明 | `app_storage.py`/`migrations/001_app.sql` 没有 TTL、自动清理，数据保留至人工删除/卷清理；架构文档仅概述可选存储 | P2 |

**重要区别**：`evidence_persisted=true` 与 `evidence_id` 表示「某次应用 Reader 回执已归档」，**不证明这份证据来自同一当前 Run、未被污染或可作为 Reviewer 授权**。Reviewer 的当前轮 provenance 门槛不能因为数据库存在记录而放宽。不得将 Incident Memory 与原始 Evidence 混为一表。

## 2. 目标与非目标

### In Scope

1. 让 **`deep_diagnosis`、`deep_diagnosis_planning`、`deep_diagnosis_skills`** 的四 Reader 回执通过现有 `app_evidence` 入库；在 Host 确实知道时记录 `graph_id/thread_id/tool_call_id`，并可查 `evidence_id`。不改 Reader 白名单/Namespace/参数/8s/16KiB。
2. 上述三个**隔离实验 Aegra Profile** 可选挂载现有 `app_routes.py:app`（不复制业务 API/表）；只有打开开关 + 运行显式迁移后业务 History 才生效。已有正式 Graph 行为保持。
3. 用**真实独立 PostgreSQL + Aegra HTTP/SSE + FakeModel/Mock MCP** 覆盖：至少正式 Agent + Planning + Skills 的证据/历史；Core Deep 有单独 Smoke（若 profile 已包含）。验证跨 Thread 不串联、同 Thread 两轮/重进、证据正确关联、运行失败与 DB 断连降级。
4. 回归 Summary 的模型输入视图/原 Checkpoint、Memory 写读撤销/HITL approve/reject（仅 Mock）、SSE reconnect、regenerate/branch；Reviewer 使用现有 S1 离线测试保证**回执兼容及原本的 UNKNOWN/fail closed**。不启动真实 Repair/付费 Provider。
5. 完成一次 #78 的**真人浏览器 M5 手工验收**（需要用户本人实际操作；AO 自动浏览器不能替代）。提交最短操作脚本/步骤，未执行时保持 `NOT RUN`。
6. 明确 Demo 存储的保留/清理策略并更新 `docs/architecture.md` 与 `docs/issue78-demo.md`，区分业务 History、Checkpoint、Incident Memory、Trace、Evidence Reviewer 的生命周期。

### Out of Scope

- 不重写 PostgreSQL Schema、Checkpoint、History Sync、前端消息渲染、Agent Graph 或 Reader 实现；除确实必要的最小适配，不做全量迁移/重复造 API。
- 不开发 Reviewer 从 Evidence DB 验证可信来源的完整机制，也不把数据库回执当可信签记；#72 S2/S3 保持独立 Issue/设计。
- 不增加 S3/MinIO、队列、Outbox/事务协调、多租户权限、复杂归档、自动删除服务、定时任务、攻击测试、用户上传 Skill。
- 不把 #75 Skills 的旧 `pinned_skills` Checkpoint Resume 缺陷算作本期修复；Skills Graph 的中间节点旧 Checkpoint 恢复仍不支持，本期只测完成 Run 后的普通聊天历史。
- 不启用真实模型、真实 Kubernetes 写/删/Repair，不修改稳定 `dev01` 资源或付费预算。

### 不变量

Reader 四工具、Namespace `kube-triage-demo`、参数验证、UID/Tool ID、8s/16KiB、Memory/Repair 的独立许可、Aegra Checkpointer 与现有客户端 SSE 契约不变。工具参数和证据原文不从模型自报 metadata 取得；只信任 Host 实际调用上下文。任何涉及真实集群写操作必须另行授权。

## 3. 增量方案与关键取舍

### 3.1 Reader 证据来源桥接（优先复用已有函数）

**推荐**：保留 `mcp_client.call_tool` 及 `app_storage.persist_evidence` 一条持久化路径，**不要复制证据 Writer**。通过现有 Deep Agents Reader Tool 的真实 Host 调用链向 `reader_context` 透传当前图/Thread/Tool Call 信息：

- `graph_id`：由构图 Profile/服务端常量绑定，不能由 LLM 工具参数声明。
- `tool_call_id`：来自执行期模型的实际 `request.tool_call.id`，在可信 `awrap_tool_call`/受控 Host 层获得；不能以模型文本正文或猜测 ID 替代。
- `thread_id`：优先从锁定版本实际注入的 `RunnableConfig` / `ToolRuntime` / Aegra runtime 获取；先用 FakeModel + Aegra HTTP 探针**实际证实**属性来源及跨异步调用传播。不能把 `configurable` 中未核实字段视为一定存在。
- `run_id`：仅在该版本执行上下文确有值时赋值；否则 `NULL`，**不是核心 Gate 的硬性要求**。

**最小改造落点**：`app_storage.reader_context` 可扩展接纳可信 `thread_id`；`call_tool` 在显式 thread_id 缺失时使用当前 ContextVar 的服务器运行信息（不让客户端传入任意证据映射）。在 `ReaderBoundary/PlanningBoundary/SkillsBoundary` 现有 `awrap_tool_call` 的 Reader 分支围绕 `await handler(request)` 设置上下文；必要时在最小工具适配器里注入配置，不能把复杂 Aegra factory/auth 当作新前提。优先只加**一次共享 Reader 桥接**，不在三个 Graph 分别复制业务 SQL。

**工具回执语义**：Reader 执行成功/403/404/Timeout 时同一 `ToolMessage` 的 `tool_call_id` 与持久 `app_evidence.tool_call_id` 对应；`evidence_id` 可由工具结果查询。调用预算拒绝（Reader 没真正执行）不应写成「真实 MCP 回执」。DB 写失败时照原 `evidence_persisted=false`、正常 Reader 返回、无重试。并发两个 Tool Call 不得相互覆盖上下文；使用 ContextVar 时必须做并行与取消清理测试。

> **S0 技术确认点**：当前 `deepagents==0.7.28` / LangChain 工具调用实际是否保留 `awrap_tool_call` 上下文到 `StructuredTool.coroutine`；若不保证 ContextVar 穿透，可通过 SDK 官方工具配置注入改造，但必须附实际 Trace、回执和最小测试。**禁止凭猜测的调用时序直接标 PASS。**

### 3.2 实验 Graph 的 History API 与 Web

- `aegra.phase-b1.json` / `aegra.phase-skills.json`：可选复用 `server/aegra.json` 的 `http.app="./src/kube_triage/app_routes.py:app"`、`enable_custom_route_auth=true`。仅复用同一 Aegra app，不单独开 FastAPI 服务/端口；验证同应用 `ASGITransport` 的 Thread State 访问、认证与 `graph_id` 区分。
- `APP_HISTORY_ENABLED`、`APP_EVIDENCE_ENABLED` 和 `NEXT_PUBLIC_APP_HISTORY_ENABLED` 默认关闭；隔离 Demo 显式开启并迁移。实验 Graph 不应因为业务表不可用而阻断正常 Reader/聊天。
- Web 继续用已经存在的 `use-conversation-history.ts` 合并方案；复用现有 Timeline，**不得为了 Phase 3 新增第二套 History Hook / Msg table**。普通多轮、换 Thread、刷新、regenerate 当前分支与历史分页由现有代码完成；必要时最小修正 profile/Graph ID 选择兼容问题。
- **交付选择**：可为已有 `scripts/skills_demo.py` 与 Planning Demo 增加选项/环境透传来启动带业务路由的**独立 PG Mock Profile**；更推荐复用现有测试 Compose/`docs/issue78-demo.md` 统一步骤，而不是建设一个新启动器平台。
- 正式 Graph 和实验 Graph 可以共享同一 `app_*` schema，但验收应证明 Thread/Graph 区隔，不跨实验 Graph 误合并记录。涉及相同 Thread ID 不同 Graph 的异常处理优先遵守 Aegra 的 Thread 元数据归属，不尝试自行合并。

### 3.3 跨层兼容测试矩阵（只做有增量价值的部分）

| 场景 | 最小实测 | 判定 |
| --- | --- | --- |
| 正式 Graph + Context Summary | 合成长历史触发截取/摘要/安全回退；同 Thread PostgreSQL History 不减少，Checkpoint 消息保持 | 不把送模裁剪视作数据删除；`summary` 失败不损坏历史 |
| Core Deep / Planning / Skills | 各实际调用一次 Reader，查询 Evidence `thread_id/graph_id/tool_call_id` + payload 状态；Skills 还需看到 `read_file` 但 `read_file` **不算 Kubernetes Reader Evidence** | 仅真实 Reader 写业务证据；来源 ID 对上 |
| History / Web | 两轮、分页、刷新/切 Thread、重复同步、regenerate 当前分支 | 不重复泡泡，不覆盖旧历史；SSE 实时流仍运行 |
| Memory | 正式 Graph Mock 写入、审阅、撤销、读取，业务 History/Evidence 开关双开 | Memory 不用 Evidence ID 当作审批或记忆证明 |
| HITL | Mock approve/reject/Resume，SQLite/InMemory 不冒充真实 PG；独立 PG 跑断点恢复 | 不产生真实 K8s 写入，不误恢复旧 Skills pin 状态 |
| SSE | Run streaming + disconnect/reconnect + fail/cancel | 当前 History 不虚报 completed；重连不重复调用 Reader |
| Evidence Reviewer S1 | 离线同轮签记有效/无效、成功/403/Timeout、带 `evidence_id` / `evidence_persisted` 两种回执 | 不把可查询 DB ID 提升为可信来源；未知仍 UNKNOWN |
| PG 故障/开关回退 | 开启后 stop/start 隔离 PG；单次 Reader 不重试；关闭双开关 | 业务 DB 故障有显式降级；回退继续走原接口 |

**性能成本**：`app_storage.connect` 目前一次归档会短连 PG；本期只跑少量 Demo 并测次数/耗时，不新加 Pool/异步队列。若表现正常不做性能优化；若确有瓶颈，以实测决定最小改动。

### 3.4 留存策略（Demo，无自动删除）

写入文档的实际承诺：
- `app_evidence` 保存**本次 MCP 受限快照**，不是 Kubernetes 全量日志；`app_conversation_messages` 保留 History 和旧分支版本；`app_conversations` 是 Thread 索引。没有明确 TTL，默认**随 PostgreSQL 业务卷持续保留，直至管理员显式手动清理**。
- 业务表与 Aegra Checkpoint、Incident Memory、Langfuse Cloud 记录**分别管理**，删除其中一种不代表其余随之清除；不要用不存在的级联删除来承诺合规。
- Demo 清理仅给**只读统计 SQL / 目标库核对**与可选的手工维护步骤；不在本期加入定时 `DELETE` 或自动清空卷。若用户决定删除数据，必须明确指定**隔离测试库**与范围，不能因为脚本存在就默认执行。
- 建议文档注明证据含受限日志、体积增长、默认开关、恢复/备份步骤；生产数据治理另议。
- 旧 History / Evidence 查询 API 与 schema 不因本期改变；若无迁移需求不要新增 DDL。

## 4. 文件范围与交付

优先触碰以下文件（按实际最少修改）：`server/src/kube_triage/app_storage.py`、`mcp_client.py`、`deep_diagnosis.py`、`deep_diagnosis_planning.py` / `deep_diagnosis_skills.py`（如共享边界可复用，避免三处都改）、`server/aegra.phase-b1.json`、`server/aegra.phase-skills.json`、`scripts/skills_demo.py` 与必要测试。正式 `graph.py`、`app_routes.py`、History Hook **若不需要则不改**。

新增/扩展 `tests` 中的实际 PG/Agent Protocol 集成案例，优先复用 `test_app_persistence.py`、`test_app_protocol.py`、`test_skills_protocol.py`、`test_deep_diagnosis_review.py`（以实际文件为准），并补 `docs/issue78-phase3-validation.md`（**证据记录**，不是新 Gate 来源）、`docs/architecture.md`、`docs/issue78-demo.md`。

唯一代码实施 PR：`Refs #78`。若 Reviewer 必须改变信任根、改正式 Repair 授权或重构数据协议才能通过，则停下，**不要扩展 #78 任务代替 #72**。

## 5. 实施顺序（一个 Implementation PR）

| 顺序 | 内容 | 进入下一步 |
| --- | --- | --- |
| P3-A：SDK/执行上下文 Smoke | 最新 main + #81/#83 差异；验证注入/ContextVar 的实际 run/thread/tool IDs 与 Reader 回执 | P3-G0、P3-G1 的实验结论可信 |
| P3-B：最小后端增量 | 实验 Graph Reader provenance + Aegra Profiles 业务 API 路由 + 功能开关 | P3-G1、P3-G2 |
| P3-C：联合 E2E | 独立 PG/Aegra/FakeModel/Mock，Summary/Memory/HITL/SSE/Reviewer 回归、Web 人工步骤 | P3-G3～P3-G6 |
| P3-D：最终收口 | 留存规则、架构图/说明、CI 与 Reviewer；一个 Implementation PR | P3-G7 |

本期不要求再建一个单独分期 Planning PR；在本计划合并后 AO 可一次按顺序执行 P3-A～D。设计需变更核心边界时停下报告，不因为是 Demo 而偷偷触发真实写操作或新的 Provider 费用。

## 6. Phase 3 唯一权威 Gate（不得预填 PASS）

| Gate | 真实测试方式 | PASS 标准 |
| --- | --- | --- |
| **P3-G0 基线** | 最新 main、#78/#75/#72、#80 closed、#81/#83 merged；独立 Worktree / PG | 记录 SHA/版本/已有验证，PR diff 只增加 Phase 3 缺口 |
| **P3-G1 Evidence 来源** | 实验 Graph 各至少一次真实 Mock Reader，含并行 2 调用 + 403/超时 | 查询到对应 `evidence_id`，`graph_id/thread_id/tool_call_id` 与运行事件一致；`run_id` 缺失明确 NULL；归档失败不重打 MCP，`read_file` 不入 Kubernetes Evidence |
| **P3-G2 Profile/API** | 实验 B1 与 Skills Aegra 真实 HTTP/SQL，独立 PG | History sync/list、Evidence GET 在启用时工作；关闭时原 Chat/Reader 正常，旧正式 Graph 无变动 |
| **P3-G3 历史与流式** | 真实独立 PG 两轮、分页、刷新、regenerate、SSE join、fail/cancel；浏览器自动化 | UI 无重复、旧消息/分支保存、partial 不宣称 completed；真实人工 M5 若未执行仍 NOT RUN |
| **P3-G4 原有 Agent 回归** | 合成 Summary 长历史 + Memory 审阅/撤销 + HITL approve/reject/Resume；原 pytest | Checkpoint 可正常恢复、Memory 与 Repair 授权不变，Evidence/History 不改变模型工具决策或审批 |
| **P3-G5 Reviewer 兼容** | #72 S1 签记/缺失/失败回执离线测试，并带 evidence ID 结果 | 原 Reviewer 使用当前轮签记；不凭持久 ID 判断可信，证据不足仍 UNKNOWN；Reviewer 未上线仍明确 S1 |
| **P3-G6 PG/留存/回退** | 独立 PG 重启，业务开关 OFF，迁移复跑，清理文档核对 | 数据重启后可查；恢复原路径且不动 Aegra 表；文档说明无 TTL、需授权的手动清理，不实际删除稳定数据 |
| **P3-G7 工程交付** | `ruff`/`pytest`/适用 Web lint/build/CI、独立 Review 与 Demo 步骤 | 一个 Implementation PR，逐 Gate 记录 PASS/FAIL/NOT RUN/BLOCKED/UNKNOWN，提交中文复现报告；未做人类浏览器测试不得代填 |

如 P3-G1 出现**无法获得可信 Thread/Tool Call 关联**，不可用虚构 ID 填库；选择范围内最小且经过实测的 SDK 注入适配器，不可让失败 silently PASS。若 Aegra 路由无法复用且需要第二个 Agent Server 则 STOP。否则目标是快速交付 Demo，避免安全专项目标蔓延。

## 7. 回退与交接

- 回退开关：`APP_HISTORY_ENABLED=false`、`APP_EVIDENCE_ENABLED=false`、`NEXT_PUBLIC_APP_HISTORY_ENABLED=false`（Web 构建变量改动需重建），停止实验 Profile；不删除 `app_*`、原 Aegra Checkpoint 或 Incident Memory。
- 仍需明确授权：真实 K8s 写入/删除/Repair/RBAC 修改、真实敏感日志外传、大批量付费模型调用、稳定 Compose 清理/卷删除。**本期默认仅 Mock/FakeModel/隔离 PG**。
- AO：仓库 `Vc-great/kube-triage-agent`；Issue #78；当前唯一 Phase 3 设计 `docs/plans/issue-78-phase3-integration.md`，本规划 PR 合并到 main 后才生效。从最新 main 创建 Worktree，按 P3-A～D 执行，不重复 Phase 1/2；实施 PR 关联 `Refs #78`，不提前关闭 Issue，未获授权不合并。
