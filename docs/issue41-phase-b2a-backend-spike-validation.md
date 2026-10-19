# Issue #41 · B2-A Backend Compatibility Spike

结论：**BLOCKED；不得恢复 B2-A 实施**。公开 Backend 接口支持写前拒绝，但本次候选未封闭聚合配额、同 Thread 并发 Run 和客户端 State 旁路。测试通过表示正例和阻断反例可复现，不表示 B2 安全 Gate 通过，也不证明所有适配方案都不可能。

## 基线与范围

- `git fetch origin` 后 `origin/main=cfc1699688229cab1157f4b6e669aaae8c607e7c`；PR #51 已合并。设计文件顶部仍含 Planning 时的 Proposed 字样，以实际合并事实和用户本次明确 Spike 授权为准，不据此扩展实施范围。
- AO 新建独立工作树 `kube-triage-agent-6`，从该 SHA 创建 `ao/kube-triage-agent-6/backend-spike`；未覆盖人类工作区。
- 权威范围：[Issue #41](https://github.com/Vc-great/kube-triage-agent/issues/41)、[合并设计](plans/issue-41-deep-agents-phase-b2-context-offloading.md)。前置证据：[Draft PR #50](https://github.com/Vc-great/kube-triage-agent/pull/50)，固定 Head `6bba62305f0fae400c6c1c92a9c3a3b02884e14b`，未合并；四项探针按该对象原样复制复核，没有继续其功能分支。
- CPython 3.14.6 / deepagents 0.7.28 / aegra-api 0.10.8 / LangGraph 1.2.14 / LangChain 1.4.6 / pytest 9.1.1 / Ruff 0.17.0。`uv sync --frozen --offline` 复用已有 Host 缓存，无依赖升级。
- 只新增测试和本证据，无 B2 Graph 注册、无 Aegra 配置或正式/Phase A/B1 Graph 修改，未实施 B2-A/B2-B/B3。无容器、服务或真实 DB；探针独立子进程，socket 连接与 Reader 被禁止，关闭 tracing，仅合成文本和 MemorySaver，无 Provider/Kubernetes/云 Trace 请求。

## SDK 接口与候选

源码路径相对于冻结环境 `site-packages/`，以符号名定位：

1. `deepagents/backends/protocol.py:BackendProtocol.write/awrite` 接收 `(file_path, content)`，没有 Tool ID、Thread/Run 或原子配额账本参数。默认 `awrite` 使用 `asyncio.to_thread(self.write, ...)`。Backend 实例是受支持接口；`FilesystemMiddleware.__init__` 明确拒绝已移除的 Backend factory。
2. `StateBackend.write` 生成 FileData/UTF-8 编码/时间戳并排队写入，返回 `WriteResult`，无待审批 `Command.update`。候选只调用 `super().write`，不覆写 SDK 私有 read/send/prepare，不直接操作 Pregel 内部键；只能写前审核路径和原始内容，不能声称已审核最终序列化后的 SDK 对象或确认持久化。
3. 测试内 `ValidatedStateBackend` 继承 StateBackend；通过公开 `ToolCallRequest.runtime.state/tool_call` 和 ContextVar 获取调用作用域，先检查路径、字节数、哨兵、覆盖、配额与历史 ID，再委托。async 沿用 SDK sync 委托，也实际验证 sync `graph.invoke`。ContextVar 是候选传参手段，不是跨进程事务保证。
4. SDK 在 Backend 前将相对路径、重复斜杠规范化，因此精确原始路径策略还需要执行边界；单独 Backend 无法辨别原始输入。`ScopeBoundary` 先拒绝非六个精确路径，再提供原始路径。仅检查合成敏感哨兵，不是通用 Secret 检测或完整内容安全实现。
5. Backend 其他可变方法也须封闭：`edit/aedit`、`delete/adelete`、`upload_files/aupload_files` 做测试专用拒绝；原生 upload 还支持二进制/base64。工具不可见不等于这些方法不存在。自动 eviction 两阈值均设 `None`，未开展 B2-B。
6. 新解释器绑定恰好四 Reader + Todo + read/write。#50 `profile_collision` 复现 A/B1 Profile 排除项并集仍隐藏两个文件工具；不能简单同进程重注册恢复。子进程隔离 registry，不改变原 Profile。

## 离线探针结果

源码：[Backend 探针](../server/tests/test_deep_diagnosis_b2_backend_spike.py)、[#50 契约对照](../server/tests/test_deep_diagnosis_b2_sdk_contract.py)。PASS 只限列出的离线性质。

| 场景/测试参数 | 状态 | 断言与限制 |
| --- | --- | --- |
| `valid` / `sync` | PASS | 真 SDK write/read、UTF-8 中文、State=Checkpoint；同 MemorySaver 重建 Graph 后可读。sync/async 均委托原生 write |
| `invalid` | PASS | 相对/越界/双斜杠/遍历/URL/编码/同形/NULL 路径、超 4096 字节（含多字节）、NULL 内容/合成哨兵，均无原生委托；所有历史 Checkpoint 无文件，pending_writes 无 files；错误 Tool ID 配对 |
| `limits` | PASS（顺序） | 3 次成功后第 4 次拒绝、覆盖拒绝，已有三文件不变；4096 字节恰好可接受 |
| `file_limit` / `total_limit` | PASS（顺序） | 注入更小的 1 文件/4096 总字节上限独立验证聚合分支；默认 6 × 4 KiB = 24 KiB，且写预算 3 更早触发，不能把默认不可达分支假称逐项验证 |
| `parallel_default` | BLOCKED（反例已复现） | 默认写预算 3，同 batch 四个不同路径全部成功，最终 State/Checkpoint 有 4 文件 |
| `parallel` | BLOCKED（反例已复现） | 上限 1 文件/4096 总字节/1 写，两个路径各 4096 字节均成功，总量 8192。共享进程 Lock 包住检查和原生委托仍不足 |
| `duplicate` | BLOCKED（反例已复现） | 同 batch 重复 Tool ID、不同路径，预算 1 下两次委托；历史 ToolMessage 去重不能原子预约同 batch ID |
| `parallel_conflict` | PASS（SDK 局部保护） | 原生 FilesystemMiddleware 拒绝同 batch 同路径第二次 mutation，仅一次委托；不代表保护跨路径聚合限额 |
| `same_thread_runs` | BLOCKED（有限反例） | 两个 Graph 实例共享 MemorySaver，从同一 pinned Checkpoint 并发调用，各成功写入，History 可见两个分支。未声称 latest 必然合并文件，也不是多进程服务实测 |
| `exception_before` / `cancel_before` | PASS（离线） | SDK 前抛错/实际 task.cancel，无原生委托；全历史文件和 pending writes 不变 |
| `exception` / `cancel` | PASS（接受后语义） | 合法工具步骤完成后，下一模型步骤报错/实际 task.cancel，Checkpoint 保留文件。未伪称取消回滚，未测线程池执行中取消窗口或服务重启 |
| 跨 Thread / 一致性 | PASS（内存） | 常规场景实际执行另一个新 Thread，文件为空；同 Thread 重建可读。不是只查询不存在的 Thread，不代表 Postgres 重启恢复 |
| `update_state` | BLOCKED（反例已复现） | `graph.aupdate_state` 注入 `/etc/forged.md` 和合成敏感哨兵，Backend 委托为零却进入新 Checkpoint，重建仍可见；旧 Checkpoint 不变 |
| `input_state` | BLOCKED（反例已复现） | invoke 的客户端 `files` 同样绕过 Backend 进入 State；只保护 write_file 不足 |
| `aegra_update_state` | BLOCKED（离线端点复现） | 执行冻结 Aegra `update_thread_state` 函数；仅 DB ownership 查询与 get_graph 获取器合成，Graph/MemorySaver 真实；响应含新 checkpoint_id，非法文件持久化，无 Backend 委托。未运行 HTTP/auth/真实 DB，不外推为未授权用户漏洞 |
| `backend_bypass` | PASS（候选封口） | 禁止 edit/delete/upload 的 sync 与 SDK async 委托；无调用作用域的 write 也拒绝 |
| #50 四项契约对照 | PASS（历史反例） | 写后 error 不能撤销、写前拒绝无文件、正常读写及 Profile 冲突；不代替新安全证明 |

并发探针在公开工具边界复制 State，用 Barrier 固定“多个调用已拿到同一快照”的可行调度，再用共享 Lock 包住候选检查和 SDK 提交。它证明此**快照候选**无原子配额，不证明所有 SDK 方案都失败。原生同路径保护确实存在，保留这个正例。

## 服务端缺口与停止决策

冻结 Aegra `api/threads.py:update_thread_state` 从 `request.values` 获取 dict（list 会合并），在 `threads.update` 图访问上下文中调用 `agent.aupdate_state`；候选 Backend 不在此路径上。必须服务端禁止/过滤客户端 files（含 Run input、UpdateState、Resume/分支等入口），或证明受支持的可信状态来源隔离；UI 隐藏不够。本 Spike 没有修改授权，也没有将伪造文件提升为 Reader 证据。

`models/runs.py:RunCreate.multitask_strategy` 虽声明 reject/interrupt/rollback/enqueue，字段存在不等于数据库级同 Thread 串行保障。本轮没有建立跨 Worker 可靠串行/拒绝证据，不把本地 Lock、MemorySaver 反例外推为服务保证。未实现具备 Checkpoint/取消一致性的预约账本、完整 Run 身份授权、每轮清理或最终 FileData 审核提交协议。

**GO 硬门槛仍未通过**：聚合配额/重复 ID 原子性、跨 Run/多 Worker 串行边界、所有客户端 State 入口封口、SDK 实际提交数据完整审核及持久化确认。按设计 §4.1/§6 停止。最小后续是先评审服务端入口与原子并发方案，再单独验证；不使用私有 Send、写后 error、补偿删除、依赖升级、自研 FS 或放宽 Gate。本次无可用 B2 Graph。

## 验证与交付 Gate

在 `server/`：

```bash
uv sync --frozen --offline
uv run --frozen --offline pytest -q tests/test_deep_diagnosis_b2_backend_spike.py tests/test_deep_diagnosis_b2_sdk_contract.py
uv run --frozen --offline ruff check src tests
uv run --frozen --offline pytest -q
```

本地完整验证：`uv run --frozen --offline ruff check src tests` **PASS**；`uv run --frozen --offline pytest -q` **477 passed in 53.51s**，包含本次 19 项 Backend Spike 和 4 项 #50 对照。`git diff --check` / staged diff 检查 PASS。远端 CI 与独立审阅见本 PR 描述和对应 Head 的 checks/review；没有结果前不能记 PASS。

- Issue B3/B5：**BLOCKED**；B9 是兼容性证据交付，不是功能完成。
- Aegra HTTP/SSE、Postgres 重启、TimeTravel/旧生产 Thread、多进程 Worker 并发：**NOT RUN**，没有启动 B2 服务或访问现存服务；内存重建不能冒充服务重启验收。
- B4/B7/B8、B2-B/B3、真实模型/集群：**NOT RUN / 不在范围**；真实 Usage、费用、质量及 Token 节省 UNKNOWN。
- 本地 Web lint/build：**NOT RUN**，无前端变更；远端 CI web/compose 另行核验。
- 回退：仅测试/证据，无部署入口或资源；保持 Draft，不自动合并、不关闭 #41。
