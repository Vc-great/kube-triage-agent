# Real-by-default / Mock Test-only 收口验收

日期：2026-10-12（北京时间）。执行基线重新 `git fetch origin` 后为 `2ddb18d9ea5cfd7ada471daaf34363ea417c88eb`，与调查快照一致；无开放 PR。分支 `codex/real-by-default`。独立 Git Worktree：`/Users/vc/.codex/worktrees/8c0d/kube-triage-agent/.local/real-by-default`。初始干净；实施时有本次修改，交付提交后再次核对。Git管理的独立Worktree先由Codex创建，后因会话写入范围限制移到`.local`；应用附件注册未成功，不影响Git隔离。

## 路径审计与最小决策

基线正式 Compose 默认 `mock-mcp`、API默认Mock URL和`LLM_ENABLED=false`；`real` profile只添加Reader，不覆盖URL；Graph有固定命令/Echo/模拟审批。Web仍导入DemoApprovalView。`.env.example`两项为空，而start.sh只替换已不存在的占位符；首次初始化会失败。静态快照与实际源码一致。

配置优先级为Host process env → Compose `--env-file`插值 → API environment → Python配置检查；原客户端导入时构建Mock默认客户端并缓存工具。当前正式固定production，只允许私有Reader endpoint，无隐式默认客户端。旧测试依赖固定路由；Phase2 FakeModel依赖工具协议；Phase3A检查static-fixture；Phase3B离线内存写入测试和Gate A依赖模拟，全部明确区分。

采用一个Graph、一份小配置边界、独立完整测试Compose；不增加Agent、数据库、消息队列、RAG或工具调用协议。安全边界保留四工具/Namespace/RBAC/日志长度/超时/审计、4次决策和6次执行；Repair默认关闭、写工具不绑定LLM，原固定目标/UID/proposal_id/审批/重查/不确定不重试保持。

## 文件级变更

| 文件 | 变化与关键理由 |
| --- | --- |
| `infra/compose.yaml` | Reader默认启动；api依赖Real Reader；移除两个Mock服务；模型必填；kubeconfig bind不自动创建Host目录。Repair仍显式profile。 |
| `infra/test.compose.yaml` | 独立test-only完整文件；Mock URL固定；无真实Reader、Repair、kubeconfig；模拟明确开启。 |
| `server/src/kube_triage/config.py`, `llm.py`, `server/Dockerfile` | 生产拒绝模拟、旧LLM=false、缺模型和非法URL；CMD启动前检查，直接Graph调用的配置错误传播为Run失败。 |
| `graph.py` | 删除parse_demo_command、echo、tool_request、summarize、旧approval节点；自然语言恒走标准LLM。精确repair-demo及原HITL控制保留。 |
| `mcp_client.py` | 删除Mock默认URL；延迟初始化、按URL重建缓存、每次校验endpoint；恰好四工具。配置错误不被转换成普通成功消息。 |
| `repair.py`, `mock_mcp.py`, `mock_repair_mcp.py` | 只增加test环境保护；不调整真实写策略。Mock可执行入口拒绝production。 |
| Web `messages/ai.tsx`, `demo-approval.tsx` | 删除DemoApprovalView和识别；保留RepairApprovalView及原interrupt→Resume。 |
| `.env.example`, `scripts/start.sh`, `compose.sh`, `check-ports.py`, `reset.sh`, `server/aegra.json` | 初始化随机秘密、0600且不改已有env；显式项目名；标签/端口/重置确认跟随项目；精确增加13002 CORS。reset仅修正项目一致性，本任务没有执行。 |
| `scripts/acceptance.py` | 正式Real-only smoke；实际配置/发现/认证/SSE/State/History/ID配对/中文/来源核验；不重启API、不发任何Approve。 |
| `acceptance_phase3b.py`, `eval_phase3a.py` | Gate A要求test/simulated，并在发送Approve前检查模拟提案；删除已移除Echo分支断言，替代路由/Fail Closed由单测覆盖。Phase3A要求test，不改评分公式。 |
| `server/tests/test_phase1a.py`, `test_phase3b.py`, `test_real_default.py` | 更新路由；模拟Checkpoint明确simulated=true；新增配置、缓存、启动保护、四工具stdio MCP协议及env初始化回归。 |
| `.github/workflows/ci.yml` | 两套Compose纯解析，用安全占位符；不需要真实模型或集群。 |
| `README.md`, `docs/architecture.md`, `deployment.md`, `isolation.md`, 本文 | 中文当前架构/部署/隔离/证据；不改历史阶段事实。 |

## 隔离与安全

只读预检发现稳定项目`kube-triage-agent`有4个运行容器（Reader、Postgres、Redis、历史Mock），`ragflow-lab`有5个；现有网络/卷带各自项目标签。没有修改它们。12027空闲、13001被Host node占用，选13002（未启动本次Web）。独立项目`kube-triage-real-default-review`，网络`…_private`、两个专属具名卷`…_postgres_data`/`…_redis_data`，均有该项目label，API仅127.0.0.1:12027。无Repair/Mock容器。down后本次容器/网络为空，稳定4个及ragflow5个容器仍运行。

复用Host现有Python3.13.14、uv缓存、pnpm647个缓存包（0下载）、Reader v0.0.67与GateB API镜像。API用只读源码/aegra配置挂载和显式配置检查CMD，依赖锁文件未变；这证明本次源码运行，不能称本次最终Docker镜像构建成功。启动独立新Postgres卷遇Docker存储`No space left on device`，未清理任何缓存或卷。只将该新项目数据转到新建私有`.local/review-postgres`、`review-redis` bind目录后启动成功；原两个卷保留。这是本轮私有override，不改正式持久化默认。

现有Reader文件为单context/user/cluster、`kube-triage-reader`身份、namespace=`kube-triage-demo`、0600、CA/TLS开启。JWT没有exp字段，不能凭本地exp解析判断过期；随后使用该受限身份GET本Namespace pods得到HTTP200，实测有效。临时副本在本Worktree0700`.local`/0600文件；未挂管理员kubeconfig。模型使用现有配置，不输出Key/Base URL。证据写入Git忽略0600`.local/real-smoke-evidence.json`，不提交全量Pod日志。

没有执行真实kubectl apply/delete/scale/patch/update、生成/刷新Token、RBAC修改、故障资源创建、真实Approve Resume、真实resources_scale写入、缩容或部署到已有项目。没有system prune、down --volumes或删除卷。完成只读验证后，仅对本次独立项目执行原前缀down；两具名卷和私有bind数据/证据保留。本次只有Namespace只读Kubernetes请求；Aegra新Thread/Run/Checkpoint写入发生在独立本地项目数据库。真实Repair写入：**NOT RUN（无授权且非本次范围）**。

## A01–A15矩阵

| ID | 状态 | 实测证据与边界 |
| --- | --- | --- |
| A01 | PASS | fetch后的SHA、独立Git Worktree/分支；Host只读项目/网络/卷标签及端口核对；独立review项目。 |
| A02 | PASS | 两套Compose解析；正式无Mock定义、依赖、DNS fallback；默认Reader无profile；源码URL保护回归。 |
| A03 | PASS | `test_missing_llm_fails_run_without_answer`、`test_reader_configuration_failure_fails_run`、非法URL参数化、production模拟/旧开关拒绝；错误为ConfigurationError，不产生Echo。 |
| A04 | PASS | FakeModel多轮/多工具同ID配对与模型seen断言；真实smoke另有5对IDs。 |
| A05 | PASS | 四工具、跨Namespace、参数/tail、预算重置、超时、403/401/404/连接分类、截断、审计；Schema mismatch不缓存。 |
| A06 | PASS | 离线stdio MCP真实协议发现与四工具调用，mock=true/static-fixture；测试Compose无kubeconfig。Golden dry-run12项；**未重跑12次历史模型评测或人工评分**。 |
| A07 | PASS | 内存Checkpoint/interrupt/Resume Reject/Approve/错误proposal_id、执行前重查/未知回执不重试单测；提案及结果simulated=true。新增Mock Repair stdio内存0→1。**未重跑Docker版Gate A脚本**。 |
| A08 | PASS | 写工具不绑定LLM；REPAIR_ENABLED=false单测及真实独立API运行态repair-demo返回denied、无pending/proposal/result，没有Repair调用。 |
| A09 | FAIL | uv sync PASS；Ruff PASS；pytest86 passed；Web lint0错误/18警告；两Compose解析PASS。**本地pnpm build两次失败**：sandbox字体下载失败，Host重试Turbopack子进程bind端口Operation not permitted。补充`pnpm exec next build --webpack`在Host通过编译、TypeScript和静态页面生成；未改默认构建脚本。CI单独报告，不能覆盖本地默认build失败。 |
| A10 | PASS | deepseek-flash标准Tool Calling；独立Aegra Run success、SSE end无error、State/History7个、3次模型决策/5次工具调用。 |
| A11 | PASS | 当前Namespace2个Pod；真实列表/事件/详情/日志ToolMessage，无mock=true/static-fixture；中文四段报告。没有制造故障或假设当前有故障Pod。 |
| A12 | PASS | 独立API执行层对events_list/default及resources_scale本Namespace返回error_type=policy；传输前拒绝，未发送跨Namespace或写请求。这证明应用策略，不冒称新一轮真实RBAC全面验证。 |
| A13 | NOT RUN | 未启动本次Web、无用户人工亲验；静态删除旧卡、lint通过不等于UI E2E。 |
| A14 | PASS | 当前中文文档/启动/隔离/历史边界更新；`docs/phase*`、eval/Golden、Fixtures无diff；历史12次与B06=FAIL原样。 |
| A15 | NOT RUN | Draft PR建立后补记录；独立Review待办、不自动合并。 |

## 实际命令与结果

```bash
cd server
uv sync --frozen --python 3.13
uv run --frozen ruff check src tests
uv run --frozen pytest -q
cd ../apps/web
pnpm install --offline --frozen-lockfile
pnpm lint
pnpm build
```

结果：113个Python依赖从现有能力安装；最终Ruff PASS，pytest86 passed（新增MCP拒绝测试首轮82 pass/1 fail为测试预期错误，已改为断言协议isError并通过；不隐藏该失败）。Web离线安装647包、0下载；lint18 warnings/0 errors；默认build失败如A09；补充Webpack构建PASS。

两套纯配置解析（每次指定独立项目、安全占位符）：

```bash
POSTGRES_USER=ci_user POSTGRES_DB=ci_db POSTGRES_PASSWORD=ci-placeholder-only DEMO_API_TOKEN=ci-placeholder-only LLM_MODEL=ci-placeholder-only LLM_API_KEY=ci-placeholder-only docker compose -p kube-triage-real-default-review -f infra/compose.yaml config --quiet
POSTGRES_USER=ci_user POSTGRES_DB=ci_db POSTGRES_PASSWORD=ci-placeholder-only DEMO_API_TOKEN=ci-placeholder-only LLM_MODEL=ci-placeholder-only LLM_API_KEY=ci-placeholder-only docker compose -p kube-triage-real-default-test -f infra/test.compose.yaml --profile repair-mock config --quiet
python3 scripts/eval_phase3a.py --dry-run
```

均PASS；dry-run只验证计划，无新指标。`bash -n scripts/{start,compose,reset}.sh`和`git diff --check`通过。脚本额外Ruff检查亦PASS。正式启动/核查可复现命令见deployment.md；本轮因存储使用私有runtime override，不能凭纯Compose解析宣称最终镜像构建或部署完成。

## Real只读E2E证据

命令：`python3 scripts/acceptance.py --project kube-triage-real-default-review --env-file .local/review.env --api-base http://127.0.0.1:12027`。实际API `TRIAGE_ENV=production`、URL=`http://k8s-mcp:8080/mcp`、REPAIR_ENABLED=false、REPAIR_SIMULATED=false。API内tools/list恰好`events_list,pods_get,pods_list_in_namespace,pods_log`；无Mock容器。匿名/错误Key State请求分别HTTP401。

Thread `94f4f51c-10f3-4cab-b199-aa2b68460029`，Run `878001bd-8c0d-4f86-8115-bccff7f991c7`，status=`success`，State next为空，History=7，模型3轮、工具5次。SSE有metadata/values/messages/updates/end，无error。最终中文报告有现象、证据、原因、建议。脱敏ID配对如下（第二列为ToolCall ID，第三列为ToolMessage.tool_call_id）：

| 工具 | ToolCall ID | ToolMessage ID |
| --- | --- | --- |
| pods_list_in_namespace | call_00_Ohd1FZW3YZH4D87OLrMZ4833 | call_00_Ohd1FZW3YZH4D87OLrMZ4833 |
| events_list | call_01_nOznF1vyam2PoGgKju5S9617 | call_01_nOznF1vyam2PoGgKju5S9617 |
| pods_get | call_00_OUATSatR9Boz8OuIwKMO8291 | call_00_OUATSatR9Boz8OuIwKMO8291 |
| pods_log | call_01_ek0l1iJoo0l66QleCFIL5788 | call_01_ek0l1iJoo0l66QleCFIL5788 |
| pods_log | call_02_2gsARfuwaiSJ5gfLmiZT9592 | call_02_2gsARfuwaiSJ5gfLmiZT9592 |

不提交全量SSE消息/Pod日志/模型URL/凭据。此单次只读smoke不是诊断准确率评测，不与Phase3A合成历史数据合并。未核验真实Repair Deployment副本，未使用Repairer/管理员权限补做查询，更未将其重置为0。

## 交付与待独立Review

Draft PR、Head SHA、真实CI链接在交付后补充。Reviewer重点：正式缺参的启动/Run错误边界；test保护是否与正式Compose隔离；旧Checkpoint无写入映射；Reader缓存变更；真实Repair策略无顺手改动；A09与A13缺口不能被CI/静态测试掩盖。等待独立Reviewer与用户决定，保持Draft，不自动合并。

## 60–90秒面试复盘

“这个项目是一个单用户诊断Demo。我把正式运行默认改成真实模型、原生Reader MCP和受限Kubernetes身份，因为原来只打开real profile仍可能把API连到Mock，界面看起来像诊断成功，其实没有读集群。现在正式Compose默认启动Reader，只允许项目内部endpoint；缺模型配置、Reader URL错误或生产模拟开关会明确失败，没有Echo或Mock兜底。业务仍用标准bind_tools，模型给Tool Call，执行层限制四工具、Namespace、参数和预算，再把同ID ToolMessage交回模型生成中文报告。FakeModel和Golden不能删：它们把协议、策略和已知数据变成可重复的离线回归，不依赖密钥或集群。它们与真实E2E是不同证据。此次真实只读Run有五对工具ID、SSE和Checkpoint；本地Web构建有环境失败、人工Web还没验，就如实记载。修复仍默认关闭，只有固定目标、本人审批和执行前重查，模型没有写权限。”

追问及回答要点：

1. **为什么四工具白名单之外还需要RBAC？** 模型与Prompt都不可信；执行层先拒绝非法tool/namespace/args，Reader read_only与受限RBAC再承担集群侧防线。只靠Prompt不能阻止越权，应用拒绝也不能当成完整RBAC实测。
2. **FakeModel通过能说明什么？** 能证明ID配对、路由、预算、拒绝、错误可见性和Checkpoint分支；不能证明真实模型遵守证据、服务可达或Kubernetes根因判断正确。Golden人工分数独立保存，不改分母或用smoke充数。
3. **为什么不把已有目标从1缩回0再验修复？** 会造成真实业务写入且超本次授权。未知写回执不重试；结果为1也不保证本次唯一写入或Pod Ready。原Gate B B06流程FAIL保留，后续必须新授权且本人完成审批。
