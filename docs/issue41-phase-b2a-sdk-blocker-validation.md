# Issue #41 · B2-A SDK 原子性阻断验收记录

状态：**BLOCKED / STOP；未交付可用 B2-A Graph**。本报告随兼容性证据 Draft PR 提交，Refs #41。这是执行获批设计时发现的契约差异，不是 B2-A 完成报告，也不证明 SDK 一般用途存在缺陷。

## 基线与边界

- 实施前 `git fetch origin`，实际 `origin/main`：`e243d6abed6aa5ea2f5c37c85174a710bb2f5e26`，Planning PR #49 已合并。
- AO 新建的独立干净 Worktree：`kube-triage-agent-5`；功能分支 `ao/kube-triage-agent-5/issue41-b2a` 从上述 SHA 创建。
- 批准设计：[B2 设计](plans/issue-41-deep-agents-phase-b2-context-offloading.md)；验收权威：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)。仅 B2-A，未进入 B2-B、B3 或 B1-R Pilot。
- 本次仅新增测试与本报告，正式 Graph、Phase A/B1、Aegra 配置、依赖/锁文件、冻结评测集均无修改；没有注册可用的 B2 入口。
- 本机冻结环境：CPython 3.14.6、deepagents 0.7.28、aegra-api 0.10.8、LangGraph 1.2.14、LangChain 1.4.6、pytest 9.1.1、Ruff 0.17.0。通过 `uv sync --frozen --offline` 复用 Host 缓存；未升级依赖。
- 探针使用无 Provider FakeModel、合成文本、MemorySaver；每个探针独立解释器，禁止 socket 连接且 Reader 调用直接报错；关闭 LangSmith tracing。未连接真实 Kubernetes、Provider、Langfuse，也未读取凭据或启动容器、数据库、HTTP 服务。

## 实测契约及 STOP 证据

SDK 源码位置以下均相对于锁定环境的 `site-packages/deepagents/`；具体行号仅对 0.7.28 有效。

1. `middleware/filesystem.py:1891` 的 `FilesystemMiddleware` 支持 `tools=["read_file", "write_file"]`。将 `tool_token_limit_before_evict` 与 `human_message_token_limit_before_evict` 设为 `None` 可关闭两类自动 eviction。`graph.py:_apply_custom_middleware` 按同名 Middleware 替换默认项。探针实际绑定恰好七工具，没有默认 Shell/Subagent；不代表已落实 B2 路径、内容或预算约束。
2. `profiles/harness/harness_profiles.py:_merge_harness_profiles` 对 `excluded_tools` 求并集。实测新解释器下为七工具；先构建 A/B1，再注册 B2 Profile，模型仍只有四 Reader + `write_todos`。因此同进程方案不成立，独立进程要求必须保留。
3. **关键差异**：`backends/state.py:99` 的 `_send_files_update` 调用 Pregel `CONFIG_KEY_SEND` 排队更新 `files`；`state.py:206` 的 `write` 在返回 `WriteResult` 前调用它。`middleware/filesystem.py:2347` 的 `async_write_file` 等待 `backend.awrite` 后返回 `ToolMessage`，没有可由外层守卫批准后才提交的文件 `Command.update`。
4. `reject_after` 探针使用 SDK 原生 `StateBackend` 与文件工具。外层 `awrap_tool_call` 等待 handler，观察到成功的 `ToolMessage`，随后返回同名、同 `tool_call_id=probe-write` 的错误回执。最终消息确实为 `error`，但最终 State **以及 MemorySaver Checkpoint** 中仍包含 `/scratch/note-01.md`，内容为纯合成的 `synthetic note`。这证实仅替换回执不能撤销已排队的文件状态更新。
5. 对照 `reject_before` 在调用 handler 前拒绝，最终 State 与 Checkpoint 均无文件。`accept` 则真实执行 SDK 写入、读回；另一个未执行 Thread 的 Checkpoint 不含文件。此处未证明服务重启、跨 Thread 实际运行、Aegra 客户端状态边界或新 Human 回合清理。

批准设计 §4.1 明确要求：

> 若 SDK 在 hook 拒绝前已执行写操作或无法验证状态更新的原子性，判 BLOCKED。

§6.3 同时将失败留下部分 State 列为 STOP。上述事实触发这一边界，因此停止功能实现。**没有用返回错误冒充回滚，没有修改 SDK 私有 Pregel Send，没有手写另一套文件存储，也没有放宽 Gate。** 写前校验对照可行，不等于当前设计所要求的写后效果验证与拒绝原子性已经成立。

## 可复现验证

在仓库 `server/` 下：

```bash
uv run --frozen --offline pytest -q tests/test_deep_diagnosis_b2_sdk_contract.py
uv run --frozen --offline ruff check src tests
uv run --frozen --offline pytest -q
```

- 专项探针：**4 passed**。这是 characterization 测试，明确断言阻断行为仍存在；不使用 xfail/skip 掩盖它，不代表安全 Gate PASS。
- Ruff：**PASS**，`All checks passed!`。
- 完整 pytest：**PASS，458 passed in 17.41s**（上述冻结 CPython 3.14.6 环境）。
- CI：以 Draft PR 对应 Head 的 GitHub Checks 为准，未得结果前为 **NOT RUN**。
- Web 本地 lint/build：**NOT RUN**，没有前端变更；现有 CI web 作业另行记录。
- Aegra 协议 Smoke、Postgres 重启恢复、SSE 取消/重连、TimeTravel/分支、旧生产 Thread、客户端 UpdateState 伪造文件：**NOT RUN**。SDK 原子性 STOP 已发生，不启动未获安全验收的 B2 服务。

## Issue Gate 对应结果

| Issue Gate | 本轮状态 | 实测证据与缺口 |
| --- | --- | --- |
| B3 FS 隔离 | **BLOCKED** | 原生虚拟写读与拒绝对照已测；写后拒绝仍持久化。路径/内容/大小/数量/预算、非法路径、重复 Tool ID、并行冲突等完整安全验收未实施，不能判 PASS |
| B5 安全与记忆 | **BLOCKED** | 探针断网、无 Provider、无真实 Reader；B2 证据守卫、敏感哨兵、UID/Namespace 注入、客户端伪造 State 等新 FS 安全负测未完成 |
| B9 回归与交付 | **部分完成，整体 BLOCKED** | 提交可复现证据、中文报告、Draft PR 与独立审查；Ruff/pytest/CI 按真实结果记录。尚无完整 B2-A 实现或协议验收，不可宣称 B9 完成 |
| B4 Context 协议 | **NOT RUN** | B2-B/B3 不在本轮；无 Summary/Offloading 改造，未验证完整长历史协议矩阵 |
| B7 A/B 离线 | **NOT RUN** | 未改冻结数据集，未运行 B1/B2 效果对照；没有输入 Token 节省结论 |
| B8 Real LLM + Mock MCP | **NOT RUN，未获授权** | 没有真实 Provider 请求；真实 Token、质量、费用均 UNKNOWN |

## 最小后续建议与待决策

先审阅设计修订，再继续实施；本 PR 不自行改变安全契约。可优先调查在 SDK 支持的 Backend 接口上做薄适配：所有路径、内容、配额、冲突与来源验证必须发生在原生 `StateBackend.write/awrite` 调用之前，校验实际拟写入数据，并定义无写后拒绝路径的提交契约。需要重新证明异常、取消、并行、Checkpoint 与客户端 State 更新都不会留下不合规状态。这里仅是候选方向，尚未验证，也未新增实现或依赖。

如果“写后检查失败仍可撤销”必须保持为硬要求，需要先给出受支持的事务机制兼容性证据；不能用私有 Send 改写、补偿删除或提示词替代。独立 Reviewer 只审核本 PR 的阻断复现与证据，不代表为未实施 B2-A 签发通过。未获得新决策前维持 STOP，不推进 B2-B、不合并、不关闭 Issue #41。

## 60–90 秒面试说明与追问

本项目保留原 LangGraph 诊断链路，用隔离的 Deep Agents 实验学习 Harness，避免影响 Reader、Repair 和历史 Checkpoint。B2-A 原计划只增加 StateBackend 虚拟笔记，笔记始终低信任，不能替代本轮 Pod UID 和原始 ToolMessage。检查冻结 SDK 后发现，文件写入通过 Pregel Send 直接排队，不像 Todo 那样返回可审核的 Command。我们用断网 FakeModel 做了写前拒绝、正常写读、写后拒绝三个对照：写后错误回执没有撤销文件，Checkpoint 仍持久化。按批准设计暂停，没有把测试绿色当成安全通过。下一步应先修订提交契约并验证 SDK 支持的写前安全适配。Planning/文件工具是否值得 Token 开销仍未有真实模型证据，StateBackend 也不降低原始 Checkpoint 占用；B2-B 的输入 Offloading 与真实模型对照需要另行授权。

追问：为什么不返回 error 就继续？因为消息状态和文件状态已经不一致。为什么不换磁盘或升级 SDK？这会越过既定隔离与依赖边界。为什么不证明“不可能实现”？本次只证伪批准设计依赖的写后验证假设，不宣称所有适配路径均不可能。
