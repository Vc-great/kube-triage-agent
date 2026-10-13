# Issue #11 · Gate A 验收与只读预检

日期：2026-10-13（北京时间）。独立 Worktree：`codex/issue11-gatea`；真实 base SHA `9e79cb9a75fd4c6b015e11f06cb5ff40a3753b55`（`git fetch origin main` 后的 `origin/main`）。Issue #11 为 open；开始时未检索到与 Issue #11 对应的 open PR。最初工作树干净。用户提到的 ChatGPT `issue11-gatea-design.md` 与三份草案没有在当前可读仓库/文件路径中找到，故以下以已检出的仓库和只读实时数据为准。

## 静态与离线检查

| 项目 | 结果 | 可复核证据 |
| --- | --- | --- |
| 代码/工具确认 | PASS | `mcp_client.py` 仅允许四工具，固定 `kube-triage-demo`；`pods_log` 无 `previous`；`reader.yaml` 的 Role 只有 pods/events get/list 与 pods/log get；`config.toml` 为 read_only。Repair 和 Graph 无本次 Diff。 |
| Manifest 静态检查 | PASS | `server/.venv/bin/python scripts/check_issue11_manifests.py`：3 个单文档 Pod、固定 Namespace、唯一名称与标签、安全上下文、资源、触发条件；脚本只读取本地 YAML，没有 Kubernetes 客户端、子进程或写命令。`git diff --check` 通过。 |
| 离线单测 | PASS | 在 `server` 运行 `.venv/bin/pytest -q`：97 passed；因 Worktree 的 sandbox 缓存写权限，pytest 报 1 条缓存警告，不影响测试断言。 |
| Ruff | PASS | `RUFF_CACHE_DIR=/private/tmp/issue11-gatea-ruff .venv/bin/ruff check src tests ../scripts/check_issue11_manifests.py`：All checks passed。首次无该设置时只因 sandbox 无权建立 `.ruff_cache` 失败，改用临时缓存后通过。 |
| 历史 Phase 3A/3B 与 CI | NOT RUN | 未重跑真实模型、旧 Golden 评分、Compose 或 CI；既有历史报告和 B06=FAIL 不改。新 PR 的 CI 另查。 |

`server/pyproject.toml` 要求 Python `>=3.12,<3.15`。Sandbox 的 `/usr/bin/python3` 为 3.9.6，不能用于本项目；Host 已有 Python 3.13.14 与 uv 0.11.21。`uv sync --frozen --offline --python 3.13` 仅用现有缓存建本 Worktree 的 `.venv`，未下载依赖、未启动 Compose 或拉镜像。

## 2026-10-13 只读集群快照

只通过现有 `ssh -o BatchMode=yes k8s-m` 执行只读 `kubectl`。context=`kubernetes-admin@kubernetes`；API Server=`https://192.168.31.136:6443`；`/readyz=ok`。未输出完整 kubeconfig、Token 或 Pod Log。Namespace `kube-triage-demo` 的 UID=`f37030f1-6b2e-4a6f-b779-45838b1c1cdd`、`part-of=kube-triage-agent`。现有 Pod：`triage-repair-demo-7d6bcf7b8-pl8vw`（UID `9dee4a17-9bf6-431f-9ef5-7bf057569429`，Running/Ready）与 `triage-sample`（UID `b8c974c4-a680-47d2-8d34-597fddafa92c`，Succeeded）；二者标签归属正确。三个 `triage-case-*` 名称未占用。目标 Namespace 未列出 ResourceQuota/LimitRange。

Reader SA `kube-triage-reader` 带项目标签且 `automountServiceAccountToken=false`；Role/RoleBinding 均只限目标 Namespace 与该 SA。以该 SA impersonation 执行 `kubectl auth can-i`（授权查询本身无资源变更）：`get/list pods`、`get pods/log`、`list events` 为 yes；`get secrets`、`create pods`、`update deployments/scale` 为 no。此项证明 RBAC 授权规则，不等于本轮实际 Reader MCP 运行态/受限 kubeconfig 身份再验证；正式四工具运行态为历史记录，本轮未连接 Reader 服务。

三个节点均 Ready，每个显示 2 CPU、1912452Ki allocatable。`kubectl top nodes --no-headers` 返回 `Metrics API not available`，因此**实时可调度余量仍未知**；allocatable 不可当成剩余。Gate B 前必须补足证据并再次检查调度约束，不得因为 YAML requests 较低就跳过。

## Gate A/B 状态矩阵

| 验收项 | 状态 | 判定边界 |
| --- | --- | --- |
| 代码/工具确认 | PASS | 仓库文件只读审查；Graph、Repair、Reader 不修改。 |
| Manifest 静态检查 | PASS | 三个隔离 YAML 与离线检查通过；不代表 API Admission 或调度成功。 |
| 集群只读核对 | BLOCKED | 身份、Namespace、名称、对象归属 PASS；节点实时余量未知，整体 Gate B 前置预检未完成。 |
| Reader RBAC | PASS | Role/RoleBinding 与目标 SA `can-i` 允许/拒绝符合最小权限；本轮未测真实 Reader MCP 调用。 |
| 独立 Review | PASS | `codex review --uncommitted` 独立检查全部变更并运行离线清单检查，未发现需修复的缺陷；这不替代真实集群验收。 |
| Draft PR | NOT RUN | 待创建并核对 draft 状态、base/head 与 CI。 |
| 真实部署 Gate B | BLOCKED | 本轮无 Kubernetes 写入授权，且节点余量证据不足；不得 apply、自动 rollback 或 cleanup。 |
| 真实模型 E2E | NOT RUN | 无三个真实故障 Pod；Phase 3A `mock=true/static-fixture` 和旧 smoke 不可顶替。 |

## 停止条件与下一轮请求

执行前若 context/API/Namespace UID 变化、Pod 名冲突、标签或 UID 异常、资源余量仍未知、需要扩权限，或任何 Manifest 影响现有 Repair 资源，立即停止相应 Gate B 操作。不得触碰 `ragflow-lab`、其他 Namespace、稳定 Compose 项目；本轮没有运行 Compose、没有真实 Kubernetes 写入、没有更改 Token/RBAC/既有资源，也没有自动清理。

下一轮需先补全只读资源余量证据，并向用户展示三份最终 YAML/Diff 与实时原状。Gate B 请求必须指明 `k8s-m` / `kube-triage-demo`、三个准确 Pod 名、逐项创建动作、总 requests/limits、重启与拉取事件噪声、可能镜像/调度失败、实际 UID 记录及回退边界；**只有用户届时明确批准**才可写入。后续删除是另一独立请求，不能从部署授权推导。真实模型 E2E 需另采集目标 UID 关联 Event、Tool Call/ToolMessage ID 和人工 Grounding 审核，不使用历史模拟分数。

**面试追问：** 为什么 `kubectl auth can-i get pods/log` 为 yes 仍不能宣称 CrashLoop 根因已查明？它只证明权限，当前 Reader 不支持 `previous`，真实重启容器日志和目标 Event 可能缺失；必须在实际 Run 中看到对应 ToolMessage 并核对目标 UID，证据不全则报告未知。
