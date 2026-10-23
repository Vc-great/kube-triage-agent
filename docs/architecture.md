# 当前架构：Real-by-default

可选的 [Issue #78 业务持久化](issue78-demo.md) 在现有 Aegra FastAPI/同一 PostgreSQL 中增加独立 `app_*` 表：Host Reader 回执写 Evidence；服务端通过 Agent Protocol 回读 State、同步用户可见 History；Web 保留 `useStream` 并按消息 ID 合并历史。`APP_HISTORY_ENABLED` / `APP_EVIDENCE_ENABLED` 和 Web 构建开关默认关闭，迁移显式执行。History/Evidence 不参与 Repair 或 Memory 的授权判定，Aegra Checkpointer 不变。

Phase 3 增量（本 PR 待合并）让隔离的 Core Deep / Planning / Skills 通过同一 `reader_context` → Evidence Writer 保存可信执行上下文中的 `graph_id/thread_id/tool_call_id`；Graph ID 固定于 Host 边界类，缺失 Run ID 保持 NULL。两个实验 Profile 挂载同一个 `app_routes.py:app`，沿用原认证和默认关闭开关。无新 schema、存储服务或 History Hook；实现及未运行项见 [Phase 3 报告](issue78-phase3-validation.md)。Evidence ID 只证明归档成功，不能代替当前轮来源签记；本 PR 增加独立 `deep_diagnosis_review` FakeModel/Mock Profile，复用 S1 原生 SubAgent/task 和当前轮校验；Aegra PG/Thread/SSE 与现有 Web 直接接入，默认不启用业务持久化。详见 [Reviewer V2 验收](issue72-reviewer-demo-v2.md)。正式 Graph、Reader 与 Repair/HITL 授权不变。

```mermaid
flowchart LR
  Web[Web / 中文报告与历史] -->|认证 Thread / Run / SSE| API[Aegra + LangGraph]
  API --> PG[(独立 PostgreSQL / Checkpoint)]
  API -. 开关启用 / Host Reader context .-> Evidence[(app_evidence / 受限快照)]
  API -. Agent Protocol State 同步 .-> History[(app_conversations / messages)]
  History -. 当前分支与分页 .-> Web
  API --> Redis[(独立 Redis)]
  API --> LLM[真实 ChatOpenAI / 标准 Tool Calling]
  API --> Reader[私有原生 Reader MCP / read_only]
  Reader --> K8s[Kubernetes / kube-triage-demo]
  API -. 精确 repair-demo / 默认关闭 .-> HITL[用户本人 interrupt → Resume]
  HITL -. 固定目标复核 .-> Repair[独立 Repair MCP]
```

Graph 仅有 `llm`、`tools`、`repair_prepare`、`repair_approval`、`repair_execute`。除精确 `/repair-demo` 外，输入均进入 `llm`，包括旧 `status`、固定英文命令和 `/approve-demo`；不生成确定性 Echo 或模拟审批。标准 `ChatOpenAI.bind_tools` → `AIMessage.tool_calls` → 策略执行 → 同 ID `ToolMessage` → LLM 中文总结。每轮最多 4 次模型决策、6 次工具执行；超预算仍为每个 Tool Call 配对错误消息。

Reader 仅 `pods_list_in_namespace`、`pods_get`、`events_list`、`pods_log`。执行层锁定 Namespace、参数契约、合法 Pod/Container 名、日志 tail 1–100（默认20）、8秒工具调用/发现超时、16KiB结果与无秘密审计。原生 Reader 配置 `read_only=true`，受限 ServiceAccount 承担集群权限边界；Prompt 不能扩大执行权限。工具发现要求恰好四工具，URL 变化会重建客户端及缓存，每次仍验证配置。

正式 Docker CMD 先检查模型与内部 URL、测试环境保护，再启动 Aegra。模型名/Key 缺失、显式 `LLM_ENABLED=false`、非法 Reader URL、正式 `REPAIR_SIMULATED=true` 阻止启动；直接调用 Graph 时同类配置错误使 Run 失败，不变成健康 AI 答案。kubeconfig 缺失的 bind 不自动创建目录；失效凭据/403/401/网络/Schema 差异属于请求期上游错误，不能生成成功工具证据或回退 Mock。`/health` 是 Aegra 服务健康，不能代替实际 Reader/模型可用性验收。

Mock 仅存在独立测试 Compose，其 API 强制 `TRIAGE_ENV=test` 并指向 Mock，Mock 可执行入口也拒绝 production。测试无 kubeconfig 挂载、无 Real Reader/Repair 服务。Fixtures、FakeModel、内存 Checkpoint 和 Mock 协议测试保留；没有第二套正式 Agent。`resources_scale` 从不绑定 LLM。Repair 默认关闭；开启后原有固定 Deployment/UID/副本、proposal_id、审批、执行前复核、未知回执不重试、写后只读回查保持。

旧完整 Thread 消息可只读展示；包含已删除节点的旧 pending Checkpoint 不保证可 Resume，禁止改名映射到 Repair 节点。旧模拟提案与真实执行的 `simulated` 不一致时拒绝，不能把历史模拟批准变成真实写入。升级后新建 Thread；不删数据库或重写历史。


持久化生命周期彼此独立：Summary 只缩小送模视图，不裁剪 Checkpoint 或业务 History；Checkpoint 保存执行、interrupt/Resume；Incident Memory 仅保存经审阅的结构化历史经验及撤销状态；History 保留用户可见消息和旧版本；Evidence 是当次受限 Reader 回执；Trace 是独立观测数据。业务表无 TTL，默认随 PG 卷保留至人工维护，不能承诺跨层级联删除。留存统计、备份恢复、需明确授权的手工清理和开关回退见 [Demo](issue78-demo.md#留存备份与手工维护)。共享 PG 故障仍会影响 Aegra 自身执行，业务归档降级不等于整个 Agent 可脱离 Checkpoint 数据库运行。
