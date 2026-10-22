# Issue #72 S1：原生 Evidence Reviewer SDK PoC 验收

本报告仅覆盖 [设计](plans/issue-72-evidence-reviewer-subagent.md) S1 / R0–R4。
所有模型与 Reader 均为离线 FakeModel / 合成回执。不是 Aegra/Web 验收、真实模型质量评估或生产安全认证。

## 基线与范围

- 2026-10-22 `git fetch origin` 后 `origin/main=87f91cb746794542c6ff677795f85d691ab747aa`。
- Planning PR [#73](https://github.com/Vc-great/kube-triage-agent/pull/73) 已合并；用户已在 AO 会话明确确认完成人工审阅并授权 S1。
- 独立 Worktree：`evidence-reviewer`；阶段分支 `ao/evidence-reviewer/sdk-spike`。
- R0 再核对 #69：Issue 仍 Open；搜索关联 PR 只见 #70/#71 规划文档，main 无 Offloading 实施模块。没有复用或改动其他 Worktree，也没有重复实现分页/Filesystem 功能。
- Host 已有 Python 3.13.14 / uv 缓存；`uv sync --frozen --offline --python 3.13` 在本 Worktree 创建 `.venv`，未下载依赖或修改共享环境。
- 安装版本：`deepagents==0.7.28`、`aegra-cli==0.10.8`、`langgraph==1.2.14`、`langchain==1.4.6`；锁文件未变。
- 新模块 `server/src/kube_triage/deep_diagnosis_review.py`，仅提供显式注入模型的 `build_graph(model, reviewer_model, checkpointer=None)`。不注册入口、Aegra 配置、开发 Profile 或 Web。

## 设计落地

复用 P0 的四 Reader 与 `PlanningBoundary` 的调用 ID、Reader/Todo 预算及输入保护。原生声明式唯一 `evidence-reviewer`，禁 general-purpose、Summary、Skills、Memory 和递归调用。默认 StateBackend 仅为 SDK 虚拟内存后端；父模型工具固定六个，Reviewer 无执行工具。

`task.description` 的所有模型原文均作为 `candidate_claim.trusted=false`。Host 在实际 Reader 执行回执上签记，签记绑定当前进程、Thread、Human 轮次、完整调用参数、工具名、ID、status 和原始内容。Manifest 只从唯一配对、签记有效的当前轮回执构造；哈希用于内容完整性，进程内 MAC 用于防止客户端/模型伪造来源。密钥只在进程内生成，不持久化或输出。

Manifest 输入最大 8 KiB、摘录单项 800 bytes，截断/丢项显式 `incomplete=true`；错误和未绑定当前 UID 的资料不能支持肯定性判定。Reviewer 的输出最大 4 KiB，枚举、字段、引用、数量和长度由 Host 校验；新增“受支持事实”、未知引用或不完整证据的肯定判定均拒绝。Task 回执再绑定 Manifest 摘要，证据 State 修改后旧判定失效。

原生 task 返回只允许同 ID 的单个 ToolMessage；不合并额外 State delta。父最终回复由确定性边界区分 `review_status` 与 advisory `verdict`，不会复制模型自称的“复核通过/根因已证实”。403 可以是已完成的 INSUFFICIENT 审查，仍无法证明目标状态。未知/失败输出不升级为可信证据或审批。

## Gate 与可重放证据

命令均在 `server/` 的锁定环境运行。子进程移除 Trace 配置并阻断 socket 连接，真实 Reader 被合成函数替换；每例独立解释器避免 Profile 并集污染。

| Gate | 结果 | 证据与边界 |
| --- | --- | --- |
| R0 | PASS | 最新 main、Issue #72/#69、合并 PR #73、固定安装版本、独立干净 Worktree 已核对；#69 差异如上 |
| R1 | PASS | `test_deep_diagnosis_review_spike.py` 实际 assembled `SubAgentMiddleware` 恰一，公开 `subagent_names` 唯一；父 FakeModel 实际六工具；原生 task/同 ID 回执；参数覆写实际到达 Reviewer；独立 P0 对照仍五工具 |
| R2 | PASS（离线 S1） | Reviewer 实际模型工具为空；伪造 `pods_get/read_file/write_file/execute/task/repair` 均拒绝；父消息/files 哨兵不进入模型输入、不被改写；新 Thread 为空；直接执行边界同样拒绝。SDK 仍传播普通 files State，不能称完全 State 隔离 |
| R3 | PASS（离线 S1） | 当前执行回执、缺/非法 MAC、错 ID/name、重复 ID/回执、篡改、伪造历史、其他 Thread/轮次、Namespace、旧 UID、403/timeout、注入日志、长证据和未知引用负测；模型自述不进入可信来源；State 修改使旧审查失效 |
| R4 | PASS（离线 S1） | schema/枚举/大小/引用校验；task 一次、并行/重复/未知类型拒绝；父 12 / Reviewer 2 / Reader 6 预算；实际定时中断及外部取消传播；非法 JSON、Provider 故障、缺 task 或来源、非法工具与 State delta 均保持 UNKNOWN，不能显示根因已证实 |
| R5–R8 | NOT RUN | S2/S3 尚未开始；没有持久化 Aegra/SSE/浏览器 Refresh/恢复、真人 Web 或 ON/OFF 质量评价证据 |
| R9 | 待阶段检查 | 本阶段 Ruff/pytest、差异与独立审查结果见 PR；不将本地检查等同全部 CI/最终交付完成 |

本阶段命令：

```sh
uv run --frozen --offline pytest -q tests/test_deep_diagnosis_review.py tests/test_deep_diagnosis_review_spike.py
uv run --frozen --offline ruff check src tests
uv run --frozen --offline pytest -q
git diff --check
```

2026-10-22 本地实测：首轮专项 62 PASS；全量 pytest **829 PASS / 118.85 秒**；随后增加的非法 Unicode 签记参数负测 **1 PASS / 54 deselected**；最终全量 Ruff 与 `git diff --check` PASS。全量运行不包含随后新增的该一条参数负测，不能将其记作 830 项全量运行。

远端 CI / 独立 Review 记录追加在阶段 PR。前端无变更，本地 lint/build NOT RUN；远端 CI 按既有流程运行，不能证明 S2 UI 已验收。

## 限制、回退与后续 Gate

- SDK isolated 默认会传递普通父 State；零工具和输出 State delta 校验只覆盖本受控 Graph。没有宣称修复 PR #68 已知的 Aegra State 写入口，也没有改变 #41 B3/B5。
- MAC 是进程内真实性机制；进程重启后旧签记不可验证，必须保持 UNREVIEWED。跨进程 Resume/重建幂等、重复计费与持久 Checkpoint 需要 S2 实测，不能由 S1 推断。
- 原生框架会在只剩零工具时省略 `bind_tools`；测试同时验证真实模型入参及执行层拒绝，不以早于过滤器的中间件工具列表冒充实际工具集。
- 超时测试用短实验值覆盖实际 wait/cancel 路径；模块默认 task 上限 20 秒。未批准真实模型调用，Token/真实时延和效果均未测。
- 支持意见仍仅 advisory；不能用第二个模型的文字证明根因。Final 使用 Host 模板，不渲染 Reviewer 的任意文本作为事实；S2 的可用性与展示仍须单独验收。
- 回退：不导入本 S1 模块即可。当前没有新增服务、端口、容器、持久数据、注册入口或部署变更，不涉及数据清理。正式 Graph/P0 文件未改动。
- 未获用户批准不得合并、关闭 #72 或绕过 STOP。只有 R0–R4 全部通过才允许进入 S2。
