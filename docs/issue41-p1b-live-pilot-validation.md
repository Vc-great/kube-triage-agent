# Issue #41 P1-B：真实 Planning OFF/ON Pilot 验收

本报告对应 [已合并的 P1-B 计划](plans/issue-41-p1b-cpa-planning-real-pilot.md)，只覆盖四个冻结 Run，不包括 P2 Formal、B2/B3、真实 Kubernetes 或 Repair。

## 基线与实现

- 实施基线：`4af1f9fc0957416d3c21ab3eda202cd4c47babd7`，Planning PR #61 已合并；[主线 CI 39424196960](https://github.com/Vc-great/kube-triage-agent/actions/runs/39424196960) 的 Python/Web/Compose 均 PASS。
- 独立 Worktree/分支：`ao/planning-pilot/p1b-live`；不启动 Aegra、真实 MCP、数据库或容器。
- 新增 `scripts/issue41_b1r_live_pilot.py`，默认无 live flag 则 BLOCKED；复用原 Runner 的 `execute`、冻结输入、Mock Reader、原生 OFF/ON Deep Agents Graph、原始模型响应安全检查、评分与私有盲审导出。
- 真实模型固定为 CPA `gpt-6-luna`，Chat Completions，输出上限 1024，SDK retry=0，无重定向/stream/隐式 reasoning 切换。精确目标采用计划中唯一已批准的 LAN 地址/端口/路径，不新增端点参数。
- 每槽独立子进程、Thread 与一条父进程预连接 socket。子进程使用 P1-A 的 `sandbox-exec (deny network*)` 与冻结继承 Transport，不能重新连接。A/B 分别最多 4/10 次，四槽合计最多 28 次；每次发送前写入独占私有 reservation 文件。单请求 60 秒、单 Run 10 分钟、全任务 30 分钟；任何 STOP 终止后续槽位，不重跑。
- 请求体上限 128 KiB、响应体上限 512 KiB；真实 Usage 与 SDK Usage 配对。没有可信的真实输入 Token/账单上界，均标 UNKNOWN，不使用 P0 合成费率或 Token 保留值冒充真实约束。
- 输出目录新建 0700、文件 0600，拒绝路径穿越/符号链接/覆盖；Key 仅进程内注入，子进程清空环境并关闭遥测。公开报告不包含模型原文、私有审计或密钥。

## 离线验证

环境：macOS arm64、CPython 3.13.14、uv 0.11.21，使用 `uv sync --frozen --offline --python 3.13` 复用本机缓存，无依赖升级。

| 检查 | 状态 | 证据 |
| --- | --- | --- |
| P1-B 专项 | PASS | `uv run --frozen --offline pytest -q tests/test_issue41_b1r_live_pilot.py`：35 passed；含四槽实际 SDK/Graph、MockTransport、Mock Reader 回放共 12 次合成 HTTP |
| P1-A / 原 Runner 回归 | PASS | 三个专项模块初次联合执行 153 passed；原有 OS 测试确认继承连接可发送、任何新连接均被拒绝；新测试确认 keep-alive 关闭后不重连 |
| 失败与预算 | PASS | 302/307/403/429/500/503、超时/连接错误、Usage 缺失/错配、工具/Namespace 越权、发送前预算、墙钟到期、请求/响应体过大均停止，无自动重试 |
| 完整 Python 回归 | PASS | `uv run --frozen --offline pytest -q`：714 passed，60.80 秒 |
| Ruff / 差异检查 | PASS | `uv run --frozen --offline ruff check src tests ../scripts/issue41_b1r_live_pilot.py`、`git diff --check` |
| 实施 PR CI / 独立 Review | NOT RUN | 待实施 Head 的远端证据 |

## 真实 Pilot

当前 **NOT RUN**，尚未发送真实模型请求。执行前再次核对最新 main CI 与全部安全 Gate。

固定顺序为 `R05-uid-injection-rep1-B`、`R05-uid-injection-rep1-A`、`R01-crashloop-rep1-B`、`R01-crashloop-rep1-A`。冻结 Manifest SHA-256 为 `fbd010f8fa61847efe05f84a98d1991b4ef238ea43cba20c82eecef79155df1f`，其他输入通过原 `_load_frozen()` 校验。

后续按实际结果补充：每槽质量/安全规则、Todo 更新与 Replanning、Reader 与 UID/Tool ID、模型回显、HTTP 尝试、Usage、延迟、失败及未执行槽位。人工盲审始终单列；未执行不能记为通过。

## 限制与回退

两臂 Prompt、工具表和决策预算不同，最多仅比较两种 Graph 配置，不能作 Planning 单变量因果推断；两对样本不支持统计显著性结论。自动规则检查不能替代人工诊断质量评分，模型账单与上游重试保持 UNKNOWN。历史 Phase A A08、Phase 3B B06 失败和 B2-A BLOCKED 均保留。

回退只需停用新增独立 CLI；正式 Graph、Reader 授权、Repair/HITL、Memory、Checkpoint 与现有服务无变更。PR 保持 Draft，不自动合并或关闭 #41，不进入 P2/B2/B3。
