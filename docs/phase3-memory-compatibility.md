# Phase 3-0 — Incident Memory 兼容性与安全 Gate

> 2026-10-15；独立 Worktree、合成数据、固定安装版本。原设计评审文档未在本地找到；验收范围采用本次用户提示词。报告等级：源码 + Fake/InMemoryStore + 真实 Aegra/PostgreSQL/SDK；真人 UI 审批未运行。

## 1. Executive Decision

**结论：DEMO_WORKFLOW_ONLY；Phase 3-1 为 CONDITIONAL_GO，条件是用户明确接受私有单用户 Demo 的审批风险。** Aegra 0.10.8 把 PostgreSQL Store 注入由 builder.compile() 注册的静态 Graph；合成案例经 thread-A 写入、thread-B 读取、仅重启 Aegra 后 thread-C 再读成功。真实 SSE 暴露 Memory interrupt，SDK Resume 有效。

现行产品 auth.py 只认证，不限制 HTTP Store 写入。有效 Demo Key 对请求中的 Incident namespace 可以直接 PUT/覆盖/DELETE（204），但 Aegra HTTP 路由自动加 users/demo-user 前缀，实际记录不等于本探针 Graph 使用的原始 kube-triage/demo-user/incidents/v1。隔离探针的 @auth.on.store.put/delete 能使 HTTP 写入返回 403，同时 Graph 仍能写入原始 namespace。**普通 Demo Key 仍可自行调用 Run/Resume 提交 approve；这不是受独立可信人员约束的审批。** 不能以此声称“人工审批不可绕过”。若要求不可绕过审批，应停止 Phase 3-1，另行评审独立受限 Repository/表及服务端写权限；本阶段未实施。

当前阻断项是产品策略和人工授权模型，不是 Store 持久化兼容性。D0-04 按现行产品 Auth 记 FAIL；临时 hook 的 PASS 只属于隔离探针，不代表产品已修复。

## 2. BASELINE / SOURCE_MAP

- 2026-10-15 实际执行 git fetch origin main 成功；实时 origin/main=905b65a451389954b90fbc0854dd4c8b811a5dc7。独立 Worktree：/Users/vc/code/kube-triage-agent/.local/worktrees/phase3-0-memory-compatibility，分支 codex/phase3-0-memory-compatibility，从该 SHA 创建。主工作树原有未跟踪 apps/web/AGENTS.md、apps/web/CLAUDE.md 未动。这次 fetch 后 SHA 恰与旧设计基线相同，未把旧文档当实时证据。
- server/uv.lock 锁定 aegra-cli=0.10.8、aegra-api=0.10.8、langgraph=1.2.14、langgraph-sdk=0.4.6、langgraph-checkpoint=4.2.0、langgraph-checkpoint-postgres=3.1.2；本机既有 server/.venv（Python 3.14.6）通过 importlib.metadata.version() 核对 aegra-cli/langgraph/SDK/checkpoint 版本一致。未安装或升级依赖。
- server/aegra.json 注册 ./src/kube_triage/graph.py:graph 和 auth.py:auth，设置 disable_studio_auth=true；graph.py:428 为 graph = builder.compile()，没有显式 Store。auth.py:15-20 的 @auth.authenticate 将合法 x-api-key 固定映射 demo-user，没有 @auth.on.store 授权 hook。
- graph.py:102、321-340 的 /repair-demo 走 repair_prepare → repair_approval → repair_execute；kind=repair_approval，Resume 只接收 decision、proposal_id。context.py:74/130 和 context_summary.py:90/107 为 Gate A/B 的预算、摘要入口。mcp_client.py:14/87/99 只允许四个 Reader 工具（pods_list_in_namespace、pods_get、events_list、pods_log）；repair.py:146-154 将 resources_scale 限定在单独 Repair MCP。
- infra/compose.yaml 带真实 K8s MCP，未启动；infra/test.compose.yaml 有固定项目名，也未复用。Web SSE/审批入口在 apps/web/src/providers/Stream.tsx、apps/web/src/components/thread/messages/ai.tsx、repair-approval.tsx:21（command.resume）。
- 已安装 aegra_api 0.10.8 源码定位：services/langgraph_service.py:315-421（静态 Graph copy 注入 checkpointer/store），core/database.py:70-84（AsyncPostgresSaver/AsyncPostgresStore.setup），api/store.py:33/64/103/149/199（HTTP 路由），core/auth_handlers.py:63-172（hook 缺省放行），api/store.py:269-310（HTTP namespace 加 users/identity 前缀），core/auth_ctx.py:27 和 services/run_executor.py:183-188（Run 期间认证上下文）。源码来自 /Users/vc/code/kube-triage-agent/server/.venv/lib/python3.14/site-packages/aegra_api；不能替代下列实测。
- 提示词所称 kube-triage-phase3-incident-memory-design-review.md 不在本 Worktree 的 docs/，全仓库及 /Users/vc/code 搜索均未找到；本报告以用户提供的验收定义为准。

## 3. Isolation Proof / TEST_TOPOLOGY

- 启动前只读枚举 docker compose ls --all、docker volume ls、docker ps；既有 kube-triage-agent 等项目没有被启动、停止或重建。确认 project kube-triage-phase30-20261015、卷 kube-triage-phase30-20261015_phase30_pg_data、127.0.0.1:15439 和 127.0.0.1:18036 均未占用。
- 实际拓扑：scripts/spikes/phase3_memory/compose.yaml 只启动全新 pgvector/PostgreSQL 容器及独立卷（DB=phase30，端口 127.0.0.1:15439）；Host 上用锁定版本的既有 server/.venv 启动 aegra serve，API 仅绑定 127.0.0.1:18036；REDIS_BROKER_ENABLED=false。两个 Aegra 配置仅注册 spike graph，不导入产品 Graph，不连接 K8s/MCP/LLM。合成 API Key 与 DB 密码由 secrets.token_urlsafe(32) 生成在 gitignore 排除、权限 0600 的 .local/phase30.env，未使用项目 .env。
- 数据仅有 synthetic-phase30-001、synthetic-phase30-http-001 等合成记录。Aegra 只在新 DB 执行自身 Alembic 与 Store setup；隔离库用户 phase30 在该测试容器内为 superuser，此实验不证明生产最小 DB 权限。
- 实验后先核验专用卷标签 com.docker.compose.project=kube-triage-phase30-20261015，再对该已确认项目执行 down -v；专用容器、网络、卷及两个监听端口均已消失。脱敏日志和结果保存在 Worktree 的 gitignored .local/phase30-*.log、.local/phase30-results.json，密钥文件不提交。

## 4. Store Compatibility

**D0-02 PASS（离线 + Aegra）；D0-03 PASS（Aegra + 隔离 PostgreSQL）。** 已安装 LangGraph 1.2.14 的 BaseStore 签名为 aget(namespace: tuple[str,...], key)、aput(namespace,key,value: dict,index=None)、asearch(namespace_prefix, /, query=None, filter=None, limit=10, offset=0)、adelete(namespace,key)。spike graph.py:49-67 在节点通过 Runtime.store 调用；离线 InMemoryStore/MemorySaver 和服务端均运行成功。get_store() 全局函数未被本方案使用。Aegra 静态 Graph 的服务端注入由 services/langgraph_service.py:405-421 执行，不依赖产品 graph.py 显式 compile(store=...)。

服务端未配置 store.index；隔离 public.store 与 public.store_migrations 由 AsyncPostgresStore.setup() 在 Aegra 启动时建立，Aegra 使用与 Checkpointer 相同的 PostgreSQL 连接池。库中只读 SQL 实测为：prefix=kube-triage.demo-user.incidents.v1，key=synthetic-phase30-001，value.summary=Synthetic incident only。Aegra 不配置 index 时，普通 KV 与字段 filter={version:1} 成功，asearch 返回 1；没有测试语义 query，更不能把 search 称为自动 BM25/向量检索。namespace 按完整 tuple 隔离；应用仍必须负责正确派生 owner 和检查记录级授权。

| 步骤 | 实际通路 | 期望 | 实测 |
| --- | --- | --- | --- |
| A：保存 | SDK threads.create → runs.stream，Memory SSE interrupt → command.resume(approve) | 合成记录写入 raw namespace | end=success，result.status=save；记录在 public.store |
| B：读取 | 新 thread-B，经 Aegra Graph 的 runtime.store.aget/asearch | 不依赖 A 的 checkpoint | 相同 value；search_count=1 |
| C：重启后读取 | 只停/启 127.0.0.1:18036 的 Aegra，PostgreSQL 容器和卷保持；再建 thread-C | 持久化仍在 | 相同 value；search_count=1 |
| owner 隔离 | Graph 探针固定读取 kube-triage/other/incidents/v1 | 不返回 demo-user 记录 | value=null，search_count=0 |

完整合成请求及事件摘要：scripts/spikes/phase3_memory/live_probe.py；运行记录：.local/phase30-results.json 的 default、restart 字段。thread-A/B/C ID 在该文件，分别独立。结果文件 gitignored，报告表格保留关键事实。

## 5. Store API Security

**D0-04 FAIL（现行产品 Auth 的 Incident HTTP 写策略）；隔离 hook 探针 PASS。** 固定版本真实路由：PUT/GET/DELETE /store/items、POST /store/items/search、POST /store/namespaces（aegra_api/api/store.py）。对应 @auth.on.store.put/get/delete/search/list_namespaces hook 在路由内调用；没有 hook 时 core/auth_handlers.py 缺省放行。产品 auth.py 当前仅检验 x-api-key；同一 Key 的所有请求都变成 demo-user，不能由 Key 本身区分“图内受审写入”和“HTTP 直接写入”。

以下为对请求 namespace [kube-triage,demo-user,incidents,v1] 和 synthetic-phase30-http-001 的真实 HTTP 状态；“覆盖”将 value.version 从 1 改为 2，之后删除。无凭据/错误 Key 的写请求未产生记录。

| 模式 / 身份 | GET 起始 | search | PUT 新建 | PUT 覆盖 | GET 后 | DELETE | GET 最终 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 产品 auth.py，无凭据 | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| 产品 auth.py，错误 Key | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| 产品 auth.py，有效 Demo Key | 404 | 200 | **204** | **204** | 200/version=2 | **204** | 404 |
| 临时 auth_guard.py，无凭据 | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| 临时 auth_guard.py，错误 Key | 401 | 401 | 401 | 401 | 401 | 401 | 401 |
| 临时 auth_guard.py，有效 Demo Key | 404 | 200 | **403** | **403** | 404 | **403** | 404 |

关键 namespace 边界：产品配置未设 store.scopes，Aegra HTTP 的 apply_namespace_scoping() 自动把上述请求落在 [users,demo-user,kube-triage,demo-user,incidents,v1]。因此有效 Key 的默认 204 **不能直接覆盖本探针 Graph 的** [kube-triage,demo-user,incidents,v1]；对 Graph 原始记录的 HTTP GET 为 404。若后续 Graph 选用 HTTP 可达的 users/demo-user/... 路径，则这些 204 将直接绕过 Memory Review。当前默认路由允许创建/覆盖/删除“Incident”名下的 HTTP Store 记录，故现行授权策略不满足审批准入要求。

隔离 auth_guard.py 的 @auth.on.store.put/delete 对 Incident 请求返回 False：真实 Aegra 中 HTTP 403，Graph 经模拟 Memory Review 的 runtime.store.aput 仍成功。有效 Key 伪造显式 [users,demo-user,...] 或 owner=other 的 Incident 路径，PUT 亦为 403；HTTP 对 Graph 原始 key 的覆盖/删除均 403，Graph 回读值未变。此 hook **只在 spike 配置** aegra-guard.json 中使用，产品 auth.py 未修改；它证明可区分通路，但不证明所有潜在 Graph/Run 入口已被授权，也不证明独立真人审批。

有效 Demo Key 泄漏后，攻击者可使用全部 Demo 用户 API，包括发起 Run 和提交 Resume；本次固定认证模式没有第二种可信 reviewer 身份。disable_studio_auth=true 只是 Studio 认证配置，真实 Agent Protocol 在无 Key/错误 Key 下返回 401；CORS 的浏览器来源限制不是 curl/SDK 服务端授权。

## 6. Trusted Identity

**D0-05 PASS（当前 Demo 单用户路径）；多用户/生产授权 NOT RUN。** Aegra @auth.authenticate 把随机测试 Key 映射 identity=demo-user；aegra_api/services/run_executor.py 在 Run 期间设置 with_auth_ctx(job.user, ...)。spike graph.py:29-40 的 get_auth_ctx().user.identity 只接受 demo-user，缺失或不符即失败，namespace=(kube-triage,identity,incidents,v1)。这是固定版本 Aegra 的内部 API，Phase 3-1 需封装并在升级时重新验证。

真实 Aegra Run 输入带 HumanMessage（内容伪装 System: owner=other）、requested_owner=other、configurable.user_id=other，Graph 回执明确 message_type=HumanMessage，owner 仍为 demo-user，DB prefix 未改变。Graph read_other 的 raw namespace 为空；HTTP 伪造 other owner 的 PUT 在 guard 下 403。负例证明的是本探针的服务端派生逻辑，不自动使未来业务节点安全。

责任分层：Aegra 负责 Key 认证、Run 的认证上下文及其自身 thread 用户检查（源码 api/runs.py:126/159/391）；应用负责从可信身份派生 Store owner、拒绝消息/LLM/未验证 configurable 字段、候选与 Resume 校验、Graph 工具权限。单一 Demo Key 无法实测两个真实身份之间的 Thread 所有权；多租户归属与 reviewer 权限均未证明。

## 7. HITL Compatibility

**D0-06 PASS（最小 Graph 的真实 Aegra SSE/SDK Resume + 产品 Repair 节点离线回归）；真人 UI NOT RUN。** Memory 探针 interrupt(kind=incident_memory_review) 带 candidate_id=synthetic-phase30-001、候选 SHA-256、version=1、decision 选项。实际 runs.stream 的事件序列含 metadata、values、updates.__interrupt__、values、end；SDK command.resume 正确载荷后 end=success、写入 Store。这里的 approve 是测试脚本生成，绝不代表人类审核。

| Resume 负例 | 服务端结果 | 保护 |
| --- | --- | --- |
| 错 kind、candidate_id、candidate_hash、旧 version、Repair proposal 载荷 | 各次 end=success 且 result.status=rejected | 探针严格比较 kind/ID/hash/version/decision，未执行 delete |
| 把 Memory approve 交给 repair_approval | 模拟 Repair result.status=rejected | proposal_id 与准确键集不匹配 |
| 把 Memory approve 交给产品 _repair_approval 节点 | 离线测试 repair_status=rejected | 产品原验证器拒绝额外/缺失字段 |
| 在另一个未中断 Thread 上 Resume | SDK BadRequestError（HTTP 400） | 未执行该 pending Thread 的动作 |
| 已完成后重复 Resume | SDK BadRequestError（HTTP 400） | 此最小流程不二次写入 |

现有 /repair-demo 实际 kind=repair_approval、proposal_id 来自 graph.py:321-340。spike 的 Repair 分支仅模拟同一验证形状，不包含 repair_execute 或 Kubernetes 能力；另有 test_phase30_spike.py 调用产品真实 _repair_approval 验证交叉负例。现有 test_phase3b.py 的 Fake/Mock Checkpoint/Resume 回归及全量 pytest 均通过。尚未验证同一正式 Graph 内两类 interrupt 共存、服务重启期间挂起 SSE 重连、真实前端 UI 审批；Phase 3-1 必须补测。当前内存 SSE broker 只用于单进程隔离测试，不能据此推断生产 Redis broker 重连语义。

## 8. Gate Matrix

| ID | 状态 | 证据 / 阻断 |
| --- | --- | --- |
| D0-01 | PASS | §2：实时 fetch、origin/main SHA、独立 Worktree、锁/安装版本和源码入口。 |
| D0-02 | PASS | §4：固定版本方法签名、InMemoryStore 离线探针、Aegra runtime.store 调用与字段过滤。 |
| D0-03 | PASS | §4：真实 Aegra + 专用 PostgreSQL，A 保存 → B 读取 → 仅重启 Aegra → C 读取，public.store 行核实。 |
| D0-04 | FAIL | §5：现行 auth.py 下有效 Key 对 Incident 请求 PUT/覆盖/DELETE 均 204；临时 hook 403 是 spike 证据，未进入产品。 |
| D0-05 | PASS | §6：Run 认证上下文实际给节点 demo-user；HumanMessage/System 伪装、requested_owner、configurable.user_id 负例未改变 owner。 |
| D0-06 | PASS | §7：真实 Aegra SSE/Resume 的最小双 kind Graph；错误/跨类型/重复/错误 Thread 负例；产品 Repair 校验器离线负例。正式组合 Graph 与真人 UI 未运行。 |
| D0-07 | PASS | §3：项目/端口/卷事前枚举，新资源标签核对后精确清理；无 K8s/MCP/LLM 连接。 |
| D0-08 | PASS | §7、§12：现有 Repair Fake/Mock、Gate A/B 及全量 pytest、ruff 均通过；无正式生产 Graph 改动。 |
| D0-09 | PASS | §9：选择 DEMO_WORKFLOW_ONLY，明确 A/B/C 分支与当前安全边界。 |
| D0-10 | BLOCKED | §1、§10：技术准入最多 CONDITIONAL_GO，须由用户决定是否接受单用户 Demo 的同 Key 自行 Resume 风险；若要求硬审批则 NO_GO。 |

## 9. Architecture Decision Record

**本次选择 B：DEMO_WORKFLOW_ONLY。** A — SUPPORTED_ENFORCEABLE 的局部条件（HTTP Incident 禁写而 Graph 可写）已在隔离 hook 下成立，但“无等价易绕过路径”不成立：同一 Demo Key 可发起合成候选 Run 并提交 approve Resume，且产品默认 auth.py 还未配置 hook。不能把 A 当成现行产品结论。

若用途严格限于私有单用户 Demo，用户接受 API Key 持有人等同该用户可自行审核，并在 Phase 3-1 加入生产 auth hook、owner 派生和服务端候选校验后，可继续原生 Store；这只能称工作流审核。对外声称不可绕过的审批、多租户或非 Demo 环境属于 C — BLOCKED_REDESIGN_REQUIRED：应单独设计受限 Repository/表、仅服务端写凭证及独立 reviewer 授权，重新做安全 Gate。本阶段没有创建表、迁移、正式 Incident 节点或架构切换。

准确的隔离 hook 位置见 scripts/spikes/phase3_memory/auth_guard.py 的 @auth.on.store.put/delete；它只拒绝 HTTP Incident 写，Graph 的直接 runtime.store.aput 不经该 hook。因此 Phase 3-1 不能仅以“hook 存在”宣称已防旁路，必须运行当前报告的完整矩阵及新增 Run/Resume 权限测试。

## 10. Phase 3-1 Handoff

最小接口契约与停止条件：

1. Store 节点接收 Runtime.store；namespace 固定为 (kube-triage, authenticated_identity, incidents, v1)，authenticated_identity 只从受信 Aegra auth context 提取。get_auth_ctx 是本固定版本内部 API，升级必须重验。key 为服务端生成的 memory_id，value 是有界 JSON 对象，asearch 只使用已验证的 namespace_prefix、filter、limit，不预设 BM25/向量能力。
2. Memory Review 的 payload 至少包含 kind、candidate_id、candidate_hash、schema/version；Resume 由服务端与 checkpoint 内候选进行严格比对，决定只用于 Memory，永不复用 Repair/Scale 授权。必须测试错误 Thread、旧候选、重放、同 Key 自行 approve、重启中的恢复及并发提交。真实 UI 审批另做人工验收，不能以 SDK 模拟代替。
3. 若继续私有 Demo，Phase 3-1 应把隔离 hook 思路移入正式 auth.py 并对实际 namespace 的所有 HTTP 入口重跑权限矩阵；如果无法可靠拒绝 HTTP 直接 Incident 写、Graph 写入也被误拒、owner 可被消息/configurable 伪造，或 Memory Resume 能触发 Repair，立即停止。若用户要求硬安全审批，直接 NO_GO，先评审独立受限 Repository/表，不在本分支实现。
4. 保持 MessagesState.messages 的 Tool Call ↔ ToolMessage 配对和本轮原始证据不变。Memory 只作为有界、低信任历史参考注入临时送模视图，不能成为 SystemMessage 或当前 ToolMessage；Gate A/B 的 build_context_view/estimate_context 预算逻辑不变。模型仍只绑定四个 Reader MCP 工具，不经 Memory 取得 resources_scale；/repair-demo 仍是独立路径。正式接入前补充这几项集成回归。
5. 从既有评审继承的后续工作只登记：Workload 字段、先候选后 Top-K、当前证据二次核验、业务收益 A/B。本阶段未实现。

## 11. Residual Risks / Negative Findings

- 当前产品 Auth 对有效 Demo Key 的 HTTP Store Incident 请求没有写拒绝，实际 PUT/覆盖/DELETE=204；应视为产品策略缺口。Aegra 的 users/demo-user HTTP 自动前缀使其不能命中本探针原始 Graph namespace，但未来 namespace 选择改变就可能形成直接审批旁路。
- 即使把 HTTP PUT/DELETE 变成 403，同一 Demo Key 仍可启动 Run 并自己提交 approve Resume；候选 hash 是完整性校验，不是身份或真人审核证明。API Key 泄漏后的全部 Demo 权限风险未消失。
- Store hook 覆盖了已知 /store/items 写路由；没有穷尽测试所有未来路由、Graph 内其他可写路径或多用户身份。Aegra 内部 auth context API 和静态 Graph 注入行为只对当前固定版本成立。
- 隔离 DB 使用超级用户完成自动迁移/setup；生产最小数据库权限、schema 权限和真实现有实例均未检查。Redis broker 被禁用，未测 SSE 跨进程续传。
- 两类 interrupt 只在最小合成 Graph 同服务验证；正式产品 Graph 没有接入 Memory，真实前端没有 Memory 审批卡片。真实 UI 本人批准、真实 LLM、真实 K8s、真实用户日志均 NOT RUN。
- 首次在 sandbox 启动 Aegra 时，本地 DB socket 连接被系统以 Operation not permitted 拒绝；随后在 Host 仅对专用 DB/端口重试成功。该 sandbox 失败不代表 DB、凭据或 Aegra 本身失败。

## 12. Commands & Reproduction

实际命令摘要（在 Worktree 根目录；端口/项目/卷需先重新枚举，切勿直接用于已有环境）：

1. git fetch origin main；git rev-parse origin/main；git worktree add -b codex/phase3-0-memory-compatibility .local/worktrees/phase3-0-memory-compatibility origin/main。
2. docker compose ls --all --format json；docker volume ls；lsof -nP -iTCP:15439 -sTCP:LISTEN；lsof -nP -iTCP:18036 -sTCP:LISTEN。确认名称与端口空闲后，生成 .local/phase30.env（0600）：PHASE30_DB_USER=phase30、PHASE30_DB_NAME=phase30、PHASE30_DB_PORT=15439、PHASE30_DB_PASSWORD 和 DEMO_API_TOKEN 均由 Python secrets.token_urlsafe(32) 随机生成；不要使用仓库 .env 或打印值。
3. docker compose --env-file .local/phase30.env -f scripts/spikes/phase3_memory/compose.yaml config -q；同前缀执行 up -d postgres。Host 上导出 POSTGRES_USER/DB/PASSWORD/HOST=127.0.0.1/PORT、REDIS_BROKER_ENABLED=false、AUTH_TYPE=custom 与 DEMO_API_TOKEN；执行既有 server/.venv/bin/aegra serve --host 127.0.0.1 --port 18036 --config scripts/spikes/phase3_memory/aegra-default.json。日志通过 redact_log.py 脱敏。
4. 在 Host 同一环境运行 server/.venv/bin/python scripts/spikes/phase3_memory/live_probe.py default；仅重启该 Aegra 进程且保留 PostgreSQL 卷，运行 live_probe.py restart；再仅以 aegra-guard.json 启动该 Aegra，运行 live_probe.py guard。结果摘要保存在 gitignored .local/phase30-results.json；本报告 §4-7 记录预期与实际。SDK runs.stream 的确切参数、HTTP CRUD body、负例均在 live_probe.py 中。
5. 在 Worktree 的 server/ 目录以 PYTHONPATH=src /Users/vc/code/kube-triage-agent/server/.venv/bin/pytest -q 执行；在 Worktree 根目录以 /Users/vc/code/kube-triage-agent/server/.venv/bin/ruff check server/src server/tests scripts/spikes/phase3_memory 执行。最终全量 pytest 为 **270 passed in 4.05s**，ruff 为 **All checks passed**，git diff --check 通过；其中 test_phase30_spike.py 的 7 个离线测试包含产品 Repair 审批节点的跨类型 Resume 负例。
6. 清理前检查 docker volume inspect kube-triage-phase30-20261015_phase30_pg_data 的 project 标签，再执行 docker compose --project-name kube-triage-phase30-20261015 --env-file .local/phase30.env -f scripts/spikes/phase3_memory/compose.yaml down -v。已核验项目/卷不再存在，18036/15439 无监听；其他项目未操作。

复现时必须使用完全新名称、独立端口/卷及合成数据；本次已删除测试 DB，故 .local/phase30-results.json 与报告中的脱敏摘要是保留证据，不能再对已删卷做查询。
