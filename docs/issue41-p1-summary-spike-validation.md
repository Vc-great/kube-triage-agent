# Issue #41 P1-S1：原生 Summary 离线证据与 STOP

本次仅交付离线 SDK 特征测试，**P1 尚未完成，S1 安全 Gate BLOCKED**。依据[已合并专项设计](plans/issue-41-p1-deepagents-native-summarization.md)，发现客户端 `files` State 写入旁路后停止 S2/Web 和 S3；没有开放 Summary Graph、添加启动入口或调用真实模型。

## 基线与环境

- 2026-10-21 重新 `git fetch origin`，`origin/main=f591bd3ba7190f4d642345b94ddbafd11512541a`（Planning PR #67）；用户明确确认人工审阅并合并。P0 PR #66 的实际主线提交为 `d031cc9`。
- 独立干净 Worktree `native-summarization`，分支 `ao/native-summarization/sdk-spike`；没有修改正式/P0 Graph、Aegra 配置、冻结 Rubric、历史 STOP 或 Checkpoint。
- 复用本机 P0 已安装环境的解释器，只读使用其依赖；`PYTHONPATH` 指向本 Worktree 的 `server/src`，不安装/升级依赖，不改其他 Worktree。Python 3.14.6、deepagents 0.7.28；Aegra 锁定版本 0.10.8。CI 使用仓库锁文件重新验证。
- 每个探针运行于独立解释器，禁 socket connect/connect_ex/create_connection，关闭 LangSmith；使用 FakeModel、合成 Reader 历史、StateBackend、MemorySaver。未读取私有 `.env`，未启动服务/容器、未连接数据库/集群或 Provider。

## 实测结果

`server/tests/test_deep_diagnosis_summary_spike.py` 使用真正的 `create_deep_agent` 与 SDK 原生 `SummarizationMiddleware`，没有自造 Summary Node。七个特征探针通过，表示行为得到复现，**不表示对应安全 Gate 已通过**。

| 探针 | 实际结果 | 边界 |
| --- | --- | --- |
| normal | 捕获工厂 assembled middleware，只有一个 Summary，且就是显式传入实例；trigger=18 messages、keep=8 messages、trim=4000；SDK 无 profile 回退 trigger=170000 tokens | 参数不等于完整 trim Token 上界实测 |
| normal | 20 条成对合成历史 + 新 Human + 最终 AI，原始 State 共 22 条；送模 10 条（含 System），cutoff=13；保留窗口边界自动保留完整 Tool Call/回执 | 模型输入压缩，原始 State messages 未裁剪；仅单 Tool Call/AI 场景 |
| normal | 模型可见摘要标记 `lc_source=summarization`；隐藏 `/conversation_history/` 文件包含历史 Tool Call ID 与 UID，可从 Checkpoint 回查 | 仅内部合成 State，无模型 read_file/write_file 工具 |
| normal | 同 saver 重建 Graph 后新一轮续答，无额外摘要；文件和事件保留，另一 Thread State 为空 | 正常 Checkpoint 续答，不等于取消后 Resume 或 Aegra HTTP/SSE |
| short | 短历史未触发摘要，没有 summary model 调用 | 仅该阈值样本 |
| profile_union | 同进程先构建 P0 OFF，再注册不排除 Summary 的 Profile，最终 Summary 实例数为 0 | 证实不能靠新 Profile 抵消既有排除项；生产/P0 未改 |
| timeout / cancel | 摘要 FakeModel 超时/取消传播，无最终模型调用、无成功 summary event；原始历史保留 | 可能已有并发 Offload 写入；不宣称事务回滚 |
| offload_failure | Backend 返回 WriteResult(error)，SDK warning 后仍调用最终模型，提交 event，file_path=None，没有文件 | **BLOCKED/DEGRADED**，不可将无 Offload 视为来源可恢复；测试不吞错伪装安全集成 |
| state_bypass | 真实安装的 Aegra `update_thread_state` 端点函数接受 `files`，将 `/outside/forged.md` 合成文件写入 Summary Graph Checkpoint，未运行模型 | **STOP：客户端 State 写入边界未封闭**；仅身份 DB 查询与 graph acquisition 被 mock，不是 HTTP E2E |
| state_bypass | 同次提交的 `_summarization_event` 未持久化；原始历史不变 | 不推断私有摘要字段已可注入，也不宣称所有入口已保护 |

精确模型工具名单在正常调用中验证为四个原生 Reader + SDK `write_todos`；无 Filesystem/Shell/task/Repair。历史 Reader 回执含合成 `old-uid-*`，测试验证其保留与回查，**尚未**验证摘要后重新读取当前 UID、Prompt Injection 或真实模型事实/授权判断。

## 原 Issue Gate 映射

| Gate | 结论 | 未完成项 |
| --- | --- | --- |
| B4 | PASS（上述离线子集）；完整 Gate **BLOCKED** | 多 Tool Calls/AI、实际 Reader 续答及当前 UID、长输入 trim 上界、400/429、取消后 Resume、Aegra/SSE、历史 Checkpoint 兼容未执行 |
| B5 | **BLOCKED**：客户端 files 可越过 State 写入边界 | 私有字段全部入口、敏感哨兵、Prompt Injection/摘要授权提升等完整负测未执行 |
| B6 | **NOT RUN** | 没有 Web 模式、浏览器/真人验收、SSE；Langfuse/OTel 禁外联，NOT RUN |
| B9 | 离线测试与 Ruff 结果见 PR/CI；P1 完整交付 **BLOCKED** | Web lint/build、Aegra Smoke、真实 CPA Smoke 均 NOT RUN；独立 Review/CI 以 PR 同 Head 记录为准 |

S2=BLOCKED，S3=NOT RUN（0 新 Provider Thread、0 HTTP 尝试、无付费调用；Usage/成本不适用）。S4 仅离线证据 Draft PR/CI/Review；不能声称已完成 P1-S1→S4。B3 原 BLOCKED、B8 原 R05 STOP/0 Pair、A08/B06 FAIL、P0 首轮 Responses/Cancel 失败保持。

## 复现与后续决策

在装有锁文件依赖的 `server/` 环境运行：

```bash
PYTHONPATH=src python -m pytest -q tests/test_deep_diagnosis_summary_spike.py
python -m ruff check src tests
PYTHONPATH=src python -m pytest -q
```

本次复用已有解释器实际执行上述命令。专项最终 **7 passed**，Ruff 与 `git diff --check` PASS。完整 pytest 在 sandbox 中 **763 passed / 4 failed**，四项已有 loopback 测试在 bind 时被环境拒绝；Host 定点重跑这四项 **4 passed**（两项单测及一个双参数用例，位于 `test_issue41_b1r_live_pilot.py` / `test_issue41_p1a_probe.py`），没有调用真实模型。此为分环境验证，不宣称单次完整 Host 回归已执行。

专项首轮 3 failed/4 passed 是探针对 SystemMessage 位置及私有字段持久化的错误假设，已按观察修正。未调整 SDK 或安全 Gate。CI/独立 Review 以 PR 同 Head 状态为准。

最小后续方案：先审阅独立 Aegra 入口对所有 State 写路径的封闭设计，或依据原方案改为无外部 State API 的本地 SDK CLI 演示；两者都不应将本次 STOP 重标 PASS。本 PR 没有增加代理服务器、修改 Aegra SDK 或开放本地 CLI 产品入口。等待决策后才继续实施；无需回收服务或清理共享资源。只需不启用未实现的 P1 模式即可保留 P0。

60–90 秒讲述：原生 Summary 压缩的是模型视图，原始 Checkpoint 仍保留消息；StateBackend 的历史文件属于内部合成材料，不代表对外文件接口安全。锁定 SDK 的同名替换有效，但 Profile 排除项会合并；Offload 错误仍可能继续摘要。离线功能触发不能替代 State 授权门禁，所以本次停在可复现证据，保留 P0，尚未开放 Web 或消耗真实模型预算。
