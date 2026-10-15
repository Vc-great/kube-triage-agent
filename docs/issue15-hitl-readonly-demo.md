# Issue #15：无新写入的 HITL 展示手册

## 默认：静态展示

1. 打开[真实 Gate B 原报告](phase3b-gateb-real-e2e.md)“B01–B08 矩阵”和[证据包](issue15-hitl-evidence.md)；指出 **B06=FAIL**：用户本人点击 Approve，但 Thread 和 `/repair-demo` 输入由 Codex 完成。历史报告是原始公开记录，证据包是派生解释；私有 State/SSE/日志不在本 Worktree。
2. 展示证据包 Mermaid 图，并对照 [graph.py](../server/src/kube_triage/graph.py) 的 `_route()`、`_repair_prepare()`、`_repair_approval()`、`_repair_execute()`，以及 [repair.py](../server/src/kube_triage/repair.py) 的 UID/归属校验、`write_scale_once()`、只读回查。指出 Reject 结束、Approve 执行前重查、达到 1 时 no-op，模型只绑定 [四个只读 Reader](../server/src/kube_triage/mcp_client.py)。
3. 对照 [test_phase3b.py](../server/tests/test_phase3b.py) 的 checkpoint、错 proposal、丢回执、不重复写和两个 YAML 解析回归；这些是离线模拟/单测，不是新 Real K8s E2E。Scale 零值省略先失败后修复；Reader 顶层序列修复后的 ready 是后续只读回查，不能替换当时 Graph 的 unknown。

如果已有离线依赖环境，可在本 Worktree 的 `server` 目录运行 `uv run --offline --frozen pytest -q tests/test_phase3b.py`；它只运行本地模拟和猴子补丁测试，不启动服务或连接集群。依赖不可用就展示已有源码与历史测试记录，标记本次测试 NOT RUN/BLOCKED，不下载或启动容器补证据。

## 可选：已有历史服务的只读查看

仅当历史 Aegra Thread/Run State/History **已存在于可信隔离服务**、服务归属与读取权限均已核对、不会为查看而启动服务或重新运行任务时，可用已有授权只读页面核对同一脱敏提案、Reject/Approve 与 checkpoint。不得外发凭据、展开完整内部 ID、创建新 Thread、输入命令或发送 Resume。若历史服务已关闭或记录不可访问，写 **NOT AVAILABLE**，仍按静态材料完成演示。

实时 Kubernetes 状态默认 **NOT CHECKED**。本手册不提供连接集群或改变 Deployment/RBAC/Token 的步骤；历史 [runbook](phase3b-gateb-runbook.md)只作背景引用，其操作步骤本期不可执行。静态展示或已有服务只读查看 **不等于**新的 Gate B E2E 通过；未经新授权不产生任何写入。
