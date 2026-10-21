# Issue #41 · P0 Deep Agents Core Demo

范围依据[已合并设计](plans/issue-41-deepagents-demo-closeout.md)，仅提供本机网页 Core Demo；不是 Issue #41 全部验收完成。原 `agent`、HITL、Memory、Reader 权限和历史 Checkpoint 保留，正式 `aegra.json` 不加载实验 Graph。

## 启动与退出

复用[原生开发环境](dev01-deployment.md)：准备锁定的 Python/Web 依赖、已有开发 PostgreSQL/Redis 及 SSH alias。先检查 13000、12026、15432、16379、8000 端口归属；占用时启动器拒绝启动，不停止其他项目。

根目录私有 `.env` 必须由当前用户持有且权限为 0600。模型精确为 `gpt-6-luna`，`LLM_BASE_URL` 必须匹配 [P1-A 已批准 CPA 目标](issue41-p1a-provider-contract-validation.md)，并配置对应模型 Key、Demo API Token、开发数据库密码。不要把真实 Kubernetes 数据发给 CPA。

```bash
make dev-deep-demo
make dev-status
make dev-stop
```

独立 Worktree 可直接读取已有根目录配置，避免复制私有文件：

```bash
DEV_ENV_FILE=/absolute/path/to/main-checkout/.env make dev-deep-demo
```

`DEV_ENV_FILE` 只选择私有配置源，仍须通过所有权、0600、字段白名单检查。为防 Aegra/Next 在子进程启动后引入第二份配置，此模式拒绝 `server/.env` 及 Web 的 `.env`、`.env.local`、`.env.development`、`.env.development.local`；不会删除或改写这些文件。

打开启动器打印的本机链接，默认 `assistantId=deep_diagnosis_planning`。首次只在自己的浏览器中输入本项目 Demo API Token；不要把 Token 放到 URL、截图或报告中。

`dev-status` 显示 `mode=deep-demo`、`reader=mock`、`model=real`、`repair=off`、`langfuse=off` 和 `aegra.phase-b1.json`。停用使用既有 `make dev-stop`，只回收本启动器持有的进程，不迁移或删除 Thread、Checkpoint、数据卷。

## 网页演示

顶部显示 **Mock Reader + Real LLM**。ON 绑定四个 Reader 与 SDK 原生 `write_todos`；OFF 仅绑定四个 Reader。点击“新 Thread · Planning OFF/ON”会完整重新加载并清除 Thread ID；运行期间禁用切换。不要手工把旧 Thread URL 改成另一 Graph 继续执行。

1. ON 新 Thread 输入：`这是合成演示。请只读调查 kube-triage-demo 中 crashloop-pod 和 oom-pod，核对状态、事件和日志，比较异常，用中文区分观察、推断和未知；无需修复。` 模型自主决定规划；不是每次请求都保证创建 Todo。
2. 观察 SSE 中的工具调用、回执与“诊断计划”。Todo 来自 SDK 应用后的 `todos` State；模型计划文本及“已完成”不能当作可信 Reader 证据或修复成功。
3. 等最终中文报告；刷新相同 Thread 可以恢复服务器 Checkpoint，运行中刷新由 SDK Run 元数据重连。此模式启用 `reconnectOnMount`，使 Cancel 发送服务器取消请求；原正式模式配置不变。用 New thread 清空当前消息，再输入 `你好，请简短介绍你的只读诊断能力。`，简单聊天不强制 Todo。
4. 使用顶部按钮切 OFF 新 Thread，检查 `Pod crashloop-pod`；确认仍能调用 Reader、生成中文报告，且没有 Todo。
5. 新 Thread 发起调查后点 Cancel；取消不会撤销已发生的模型费用或 Reader 请求。中断后可以新建 Thread；不要把中断残留 Todo 当成完成证据。

Mock 数据的实际 Pod 名是 `crashloop-pod`、`healthy-pod`、`imagepull-pod`、`oom-pod`。缺失目标或预算耗尽时，Reader 拒绝/停止，最终报告应承认未知。OFF 每轮 4 次模型决策；ON 10 次，Reader 最多 6 次，Todo 写入最多 5 次。启动器另设 120 秒后台 Run 超时与 0 次后台重试；单次模型网络超时/重试仍复用 `chat_model()`。

## 配置隔离与验证

新 Profile 只传允许的子进程环境，固定合成 `memory-web` MCP，禁 Repair/Memory/Context，显式设置 `use_responses_api=False`，关闭 Langfuse 自动读取、LangSmith 与 OTel，拒绝外部继承的代理和 Provider 开关。SDK 的 OpenAI Provider Profile 默认 Responses，因此仅关闭 Responses High 开关并不足够。

Worker 队列和 Redis 事件前缀使用 Worktree 路径的稳定摘要，与默认 `aegra:jobs`/`aegra:run:` 分离；FakeModel 协议 Smoke 必须使用另一套独立队列/事件前缀，且模型 Key 使用无效合成值，不能与真实模型测试复用 Worker。仍复用开发数据库，不是多实例容灾部署；不要与另一 Aegra 实例同时进行崩溃恢复/Redis 故障实验，SDK 的数据库恢复扫描不按队列过滤。

离线 SDK HTTP 契约测试：

```bash
cd server
uv run --frozen pytest -q tests/test_deep_demo_protocol.py
uv run --frozen ruff check src tests ../scripts/dev.py ../scripts/dev_preflight.py
uv run --frozen pytest -q
```

测试通过 MockTransport 捕获双 Graph 经 `create_deep_agent()` 后的实际 `/v1/chat/completions`，验证 Reader/Todo 清单、ToolMessage ID 续答和 SDK Todo State；不发 Provider HTTP。完整 Aegra FakeModel 协议检查可复用 `scripts/issue41_phase_b1_smoke.py`，须先搭建独立本机 Fake API/队列，不能直接指向真实 Provider API。

## 失败记录和剩余 Gate

2026-10-21 首轮离线 Smoke 隔离不足：Fake API 与真实 API 共用默认 Redis 队列，测试 Run 被真实 Worker 执行；SDK 默认 OpenAI Profile 又启用了 Responses。日志可观察到 **7 次 CPA `/v1/responses` HTTP 200**，输入仅合成提示词/Mock Reader，Usage UNKNOWN。已 STOP 并停止自有服务，该轮仍为 FAIL，不能追认成离线 PASS。用户明确允许最小协议/队列修正后才恢复。

修正后离线双 Graph SDK HTTP 测试和独立 Fake Aegra Smoke 已通过。网页真实合成 Smoke 验证 ON Todo、Reader、中文报告与刷新，OFF 无 Todo；首个缺失目标用例明确输出未知，但模型把“尝试读取”的步骤标 completed，不能据此认定目标已核验。另一次 Cancel 原先只停止本地流，服务器仍完成，属于本轮发现的 FAIL；新增 Demo 专属 SDK 重连配置以修复，保留原失败结果。模型效果证据仅为少量 Smoke。

P1 Summary、P2 Filesystem、额外 Formal A/B 不在本轮范围。B3 仍 BLOCKED，B4 未完成部分仍 NOT RUN，B7 历史 FakeModel 证据与 B8 原 R05 STOP/0 Pair 保留，历史 A08/B06 FAIL 不变。CI 和独立 Review 的最终状态以 Implementation PR 为准；不自动合并、不关闭 #41。
