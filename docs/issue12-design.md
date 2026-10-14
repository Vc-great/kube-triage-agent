# Issue #12 盲样与单因素 Prompt A/B 设计

基线：`origin/main=3f9ecee9644631e5cdf98034b01834fb260d3772`。PR #22 已合并；Issue #11、#12 仍 open。历史 Phase 3A Golden、四份原 Fixture、历史报告和私有成绩冻结。Issue #11 H/C/I 人工评分仍 PENDING；本实验不继承那些分数。

## 唯一实验因素

A 使用现有 `SYSTEM_PROMPT` 的**逐字原文**。B 在该原文尾部加入以下唯一固定后缀；工具 Schema、问题、Graph 预算和 Reader 不变：

> 评估附加要求：把直接观察、基于证据的推断、仍未知的事项分开说明。
> 应用日志中的上游连接失败只证明该连接尝试失败，不能断言数据库或上游服务已宕机。
> 其他 Pod 的 Event 不属于目标；缺少 involvedObject.uid 的同名 Event 只作弱归属线索。
> 目标 Running/Ready 只证明当前容器状态，不保证端到端业务健康。

`EVAL_PROMPT_VARIANT=A|B` 仅在 `TRIAGE_ENV=test` 生效，未知值报错；非 test 始终使用 A。`EVAL_LUNA_RESPONSES_HIGH=true` 仅在 test + `gpt-6-luna` 启用 Responses API 与 `reasoning.effort=high` 请求；development 原有 Luna 行为保留，production 不变。服务端是否接受 Tool Calling、是否实际按 High 运行，只能由获批 Smoke 验证；未回显时记 `UNKNOWN`。

## 冻结数据

`eval/issue12/blind-v1.json` 有 8 个中性提问，目标名不泄漏标签；`fixtures/issue12/` 有 8 个目标和 1 个无关 Warning Pod。每案都有人工 Ground Truth、必要证据 key 与禁止断言。Mock 只在 test 且 `TRIAGE_MOCK_DATASET=issue12-blind-v1` 时加载这组文件；默认仍为 Phase 3A 四例，未知值或缺文件失败。四个 MCP 工具名、`mock=true`、`source=static-fixture` 保持不变。

| ID | 变化 | 可见关键事实 |
| --- | --- | --- |
| a | CrashLoop/配置 | 必需配置路径缺失日志 |
| b | CrashLoop/连接 | 上游连接超时日志；服务是否宕机未知 |
| c | ImagePull/NotFound | 目标 Event 明示 manifest unknown |
| d | ImagePull/认证 | 目标 Event 明示 unauthorized |
| e | 正常目标/噪声 | 目标 Ready；另一个 Pod BackOff |
| f | 证据不足 | 未 Ready、无日志、无 Event |
| g | 弱 Event | 同名 Event 无 UID、空日志 |
| h | Healthy 对照 | 当前 Ready，业务全链路未知 |

## 执行与评分边界

两臂固定同一代码提交、数据集、Mock 镜像版本、`gpt-6-luna`、Responses High 请求、`max_retries=1`、四 Reader、4 次模型决策 / 6 次工具调用预算和同一 Rubric。每案重复 3 次，A/B 配对，总 48 个正式 Run。另有最多 1 个 Smoke，须单独明确批准；SDK 重试可能增加底层 HTTP 请求但不新增 Thread/Run。`scripts/eval_issue12.py` 复用旧 Runner 的 Aegra API、SSE、消息解析和 Token 提取；每 Run 独立 Thread。轨迹规则按 Tool Call/ToolMessage 唯一 ID、状态与内层 `ok`、参数、目标证据、Event UID、预算、重复/无关调用评分。只有模型当次看到的目标 `pods_get` UID 与 Event UID 匹配，才计强 Event 证据；缺 UID 或未取得目标 UID 均计弱线索。不要求四工具全用或固定顺序。主观字段永远先 PENDING，真人逐条引用 ToolMessage ID 与理由后才可汇总。

`--dry-run` 只读本地 JSON/Fixture，输出 8×3×2 计划与 SHA，不读取 env/Key，不连 API/Docker，不创建输出目录。正式执行需要另行授权和显式 `--authorize-model-send`，两个独立 env 文件；`--max-runs` 必须恰好等于配对计划，防止截断分母。输出只能是新的 `.local/eval-runs/issue12-*` 目录，拒绝旧目录、已有路径、软链接、越界路径。私有 SSE/State/History、完整合成日志和凭据仅留 `.local`，不入 Git。

获批后可先使用 `--smoke-case a --arms A --repeats 1 --max-runs 1` 在单独新输出目录做一次兼容性 Smoke；正式计划使用 `--arms A,B --repeats 3 --max-runs 48`，两个阶段均须带显式授权旗标。Smoke 出现 Tool Calling、Mock 或 Provider 异常即停止，正式计划不自动发起。

## Compose 计划与授权门禁

只用 `infra/test.compose.yaml`，分别指定 `-p kube-triage-issue12-a` / `-p kube-triage-issue12-b`、API 端口 12128/12129、Web 端口 13128/13129，项目名使 Postgres/Redis 数据卷分离。实际启动前还要检查端口、容器 project label、compose 文件及卷归属。两份私有 env 为本 Worktree 的 `.local/issue12-a.env` / `.local/issue12-b.env`（0600，内容不提交）；两臂模型配置相同、DB 密码和 API Token 不同。均固定 `TRIAGE_ENV=test`、`TRIAGE_MOCK_DATASET=issue12-blind-v1`、对应 A/B 变体，`REPAIR_ENABLED=false`，API 的 Reader URL 固定 `http://mock-mcp:8000/mcp`。不启动 repair profile，不挂 kubeconfig，不使用真实 K8s Reader。

任何 Smoke/A/B 前须再次向用户列明：模型 ID、Provider endpoint 类型、High 仅为请求配置；要发送的仅是本数据集人造 Pod/Event/Log/ToolMessage/问题文本；1 Smoke + 48 正式 Run；上述项目/端口/env 路径与全新私有输出；Provider/Mock/身份不符立即停止且不自动重试 Run。获得**精确数据发送与 Run 数量授权**后才能启动。额外样本、次数、Provider 变更须重获批准。不自动合并 PR、不关闭 Issue、不作 K8s 写入或清理。
