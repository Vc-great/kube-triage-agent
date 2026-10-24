# Issue #69 Phase A：原生 Virtual Filesystem 验收与运行说明

范围：仅 [V2 设计](plans/issue-69-deepagents-filesystem-offloading-demo.md) §6 V2-A0～A5；Implementation PR A，Refs #69。Phase B 未实施，Issue #69 保持 Open，未经批准不合并。

## 基线与环境

- 2026-10-24 fetch 后 `origin/main=7b3a9bd8a507145a95fe39e5b47f173a9673d48e`；Planning PR #89 实际已合并（Issue 和设计中的“待合并”文字是历史状态）。
- 独立 Worktree `/private/tmp/kta-issue69-phase-a`，分支 `ao/vc-great-kube/phase-a`，无主工作树 dotenv；不改正式/B1/Skills/Reviewer Graph、Reader 白名单/Namespace/16KiB/8s、HITL/Memory/Repair。
- macOS arm64，Python 3.13.14；`uv.lock`：Deep Agents 0.7.28、Aegra 0.10.8、LangChain 1.4.6、LangGraph 1.2.14；Python/Web 依赖从本机缓存离线建立，锁文件未改。
- 复用已有 `pgvector/pgvector:0.8.7-pg18-bookworm` 镜像，独立临时容器、PG 数据、API/Web 端口和 AO session 标签；不读取真实日志/Secret，不调用真实模型或真实 Kubernetes。
- 代码 SHA 以本报告所在 PR 的 head 为准；CI 和独立 Review 针对该 head，后续文档提交不改变功能代码。

## 实现与锁定 SDK 实测

新增唯一 opt-in `deep_diagnosis_offload` Graph，当前只有 Phase A notes 行为，没有 Phase B 模式或 JSONL 适配器。复用 `create_deep_agent`、原生 `StateBackend()`、PlanningBoundary 的 Reader/Todo 校验及现有启动器。

SDK 通过 middleware `name` 原位替换，测试捕获最终 `create_agent(middleware=...)`：恰一个原生 `FilesystemMiddleware`；其四个工具的 coroutine 均来自锁定 wheel 的 `deepagents/middleware/filesystem.py`，没有自建同名工具。传入 `tools=[ls,read_file,write_file,grep]`，模型绑定工具捕获恰为四 Reader + Todo + 四文件工具（9 项）。隐藏工具也不在可执行工具节点中，伪造 `execute/shell/edit_file/delete/task/glob/repair` 调用产生 error。

`tool_token_limit_before_evict=None` 与 `human_message_token_limit_before_evict=None` 关闭本图自动卸载；长而有界的合成 Reader 结果仍直接内联，无 `/large_tool_results/`。关闭 Summary、Skills、Memory、Subagent。新图采用独立 `notes_fake` Profile 标识，避免 SDK 全局 Profile 排除项与其他实验混用。

文件边界只允许标准化绝对 `/notes/` 路径，拒绝路径穿越、反斜杠、重复斜杠、控制字符、根目录和内部 Offload 路径。每轮 8 次文件尝试、其中 4 次写尝试；单次 UTF-8 正文 ≤8192 bytes；读取 offset 0..8192、limit 1..100；grep 最多100项，默认路径收窄为 `/notes/`。预算包含失败尝试且按模型调用顺序计算，平行调用也确定；Reader 6次、Todo 5次预算独立保留。模型决策上限20次，Aegra 入口配置 recursion_limit=100。

SDK `StateBackend` 的 `files[path].content` 实测是字符串。原生 `write_file` 支持覆盖原路径，测试保留该语义；这不是 Phase B 自动卸载路径覆盖策略。文件内容仅是模型工作笔记，不替代当前轮配对成功的 `pods_get` 证据，也不授权 Repair。

FakeModel 根据真实 ToolMessage 的成功/失败决定下一步；主流程实际调用 Todo → Mock events_list → write_file → read_file → ls → grep → Todo，再输出中文结论。读取、刷新、不存在、越界请求也实际发 Tool Call；不伪造保存成功回复。

## Gate 与证据

| Gate | 状态 | 实际证据 |
| --- | --- | --- |
| V2-A0 | PASS | fetch/PR #89 merged、上述 SHA/锁定依赖、独立 Worktree；范围 diff 不含正式 Graph/Reader 改动 |
| V2-A1 | PASS | `uv run --frozen pytest -q tests/test_deep_diagnosis_offload.py`：捕获唯一原生 FS、九工具、工具来源、无自动卸载与隐藏工具拒绝 |
| V2-A2 | PASS | 同一专项实际 UTF-8 写/读/目录/grep/非零 offset、配对 Tool ID、原生覆盖与错误；37项专项通过 |
| V2-A3 | PASS | 同一专项普通两轮/Checkpoint 读取/新 Thread、预算/路径错误；HTTP/PG 验收见 A4 |
| V2-A4 | PASS | 固定8000端点、独立API/PG/Web启动；`ISSUE69_TEST_API_URL=http://127.0.0.1:12069 uv run --frozen pytest -q -s tests/test_offload_protocol.py`：3 PASS；真实SSE/PG、普通三轮/刷新/新Thread/可见错误。AO Browser打开已完成Thread，实际显示四文件工具参数、ID、结果和中文结论；停止清理已实测 |
| V2-A5 | NOT RUN | Ruff PASS；Web修改后lint/build PASS（18条现有lint warning、既有Tailwind格式warning）；最终全量存在一项既有loopback超时，CI/独立AO Review待运行，完成后更新 |

初次全量：913 PASS / 4 FAIL / 47 SKIP，四项新增测试失败来自 SDK Profile 排除项混用；改为专用 `notes_fake` 后第二轮全量921 PASS / 47 SKIP；新增伪造输入检查后专项37 PASS，最后一轮含真实HTTP全量：924 PASS / 1 FAIL / 44 SKIP，失败为既有 `test_inherited_keepalive_loss_never_reconnects` 连接自身loopback临时端口超时；其定点重跑见PR验证记录。首轮专项的测试假设错误（正文类型、原生覆盖行为、Fake provider标识）已据实际SDK修正，不更改功能Gate。

初次HTTP主流程因试用18069触发固定Reader endpoint拒绝而FAIL；端口变更已完全撤回，经其他会话自行释放8000后固定端点重跑3 PASS，Reader白名单零修改。

AO Browser自动化检查：刷新加载HTTP已完成Thread的文件工具卡片/回执/结论为PASS；在聊天输入框fill/type后点击Send或Enter没有出现可观察的提交，新Notes Thread按钮也未产生可观察导航，未捕获页面error，原因 **UNKNOWN**，不声称浏览器发送验收PASS。真人交互验收留给#86；HTTP发送、多轮、PG读取已独立通过。

跳过的现有集成测试需要它们自己的服务与显式环境变量，SKIP 不代表 PASS。真实模型质量/费用收益、真实 Kubernetes、真人 Web QA #86：**NOT RUN**。Phase B V2-B0～B6：**NOT RUN**。旧 S1 12 PASS / 3 FAIL、**F3 FAIL / STOP 保持原始历史记录**；本 PR 不修复、不复判该历史失败。

## 启动、演示与验证

在本 PR 的干净独立 Worktree 中执行（本机应已有 Python3.13、uv、pnpm、Docker 和上述镜像）：

```bash
cd server
uv sync --frozen --python 3.13
cd ../apps/web
pnpm install --frozen-lockfile
cd ../..
make dev-deep-notes-demo
# 等同 python3 scripts/offload_demo.py
```

启动器拒绝 server/Web dotenv，清洗模型 Key、Proxy、Tracing、数据库等继承变量，强制 `TRIAGE_ENV=test`、FakeModel、Mock 数据、Repair/Memory关闭。只绑定本机：API `12069`、Web `13069`、PG `15469`、Mock MCP固定 `8000`。不读取真实 Provider 配置。端口被占用时明确失败，不杀其他进程；API/Web/PG 可通过 `--api-port/--web-port/--db-port` 更改，Mock固定端点保持原有边界。需先与其他Demo协调8000；不提供绕过白名单的参数。

打开 `http://127.0.0.1:13069`，使用本地公开测试 Key `skills-demo-local-only`；Graph为 `deep_diagnosis_offload`：

1. 新 Notes Thread 输入“调查合成事件并保存笔记”，查看现有工具卡片中的 write_file/read_file/ls/grep 参数、Tool ID与结果，以及Todo和中文结论。
2. 同Thread输入“读取笔记”，刷新页面后仍读取同一份笔记；普通“你好”不调用文件工具。
3. “新 Notes Thread”后输入“读取笔记”，应明确失败；输入“读取不存在的笔记”或“越界读取笔记”同样可见error，不声称已保存。
4. 不导入旧实验Checkpoint，不在同Thread运行重叠Run，不将笔记当作可信集群证据。

```bash
cd server
uv run --frozen ruff check src tests ../scripts/skills_demo.py ../scripts/offload_demo.py
uv run --frozen pytest -q
ISSUE69_TEST_API_URL=http://127.0.0.1:12069 uv run --frozen pytest -q -s tests/test_offload_protocol.py
cd ../apps/web
pnpm lint
pnpm build
```

独立 CI `notes` job 使用自己的 PG service、Fake/Mock Aegra，执行原生专项和真实 HTTP/SSE 测试；原有CI job继续回归其他Graph。

## 清理、回退与限制

启动终端按 Ctrl-C（或向本次启动器发送 SIGTERM），启动器只停止本次进程组并移除其随机 `kta-notes-*` 容器及临时卷；日志为本机临时合成诊断材料。普通停止后不保留本次PG，重启需新Thread。停止整个独立Demo即完成回退，无数据库迁移、无正式配置切换。不要执行共享 `docker compose down`、volume prune或停止其他Demo资源。

已知 Aegra `update_thread_state → files` 写入旁路仍未修复，本Demo不提供恶意State注入认证、不对公网/多用户部署，不接收真实敏感数据。不宣称跨Worker并行文件原子性、任意中断恢复或长期Memory。Phase A合并后也必须经用户再次批准才进入Phase B。
