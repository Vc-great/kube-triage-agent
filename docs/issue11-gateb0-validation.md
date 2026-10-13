# Issue #11 · Gate B0 只读就绪复核

日期：2026-10-13（北京时间）。本轮只做只读集群预检、离线静态检查和 Draft PR；没有 Kubernetes 写入授权。

## 仓库基线与查阅范围

- 仓库：`Vc-great/kube-triage-agent`；Issue #11 实时为 open。PR #17 实时为 **MERGED**，Gate A head `27c5b257b8e7a2973ae793aff81dac44ff14f7bb`，merge SHA `603159cc1901321af3ef202a60a0c30516f1862f`。
- `git fetch origin main` 后，新独立 Worktree 位于 `.local/issue11-gateb0`，分支 `codex/issue11-gateb0`，基线 `origin/main=603159cc1901321af3ef202a60a0c30516f1862f`。未改稳定主工作树，也未复用 Gate A Worktree。
- 已确认并查阅：`README.md`、`docs/issue11-scenarios.md`、`docs/issue11-gatea-validation.md`、三份 `infra/k8s/scenarios/triage-case-*.yaml`、`scripts/check_issue11_manifests.py`、`.github/workflows/ci.yml`、`infra/k8s/reader.yaml`、`infra/k8s-mcp/config.toml`、`server/src/kube_triage/{graph.py,mcp_client.py,prompts.py,repair.py}`、`scripts/acceptance.py`、`scripts/eval_phase3a.py`、`docs/phase3a-report.md`、`docs/phase3b-gateb-real-e2e.md`。文件均存在；本轮发现脚本仍用 `assert` 且 CI 未执行该脚本，已作最小修复。Graph、Repair、Reader、历史 Golden 与人工分数没有修改。

Gate A 的 2026-10-13 记录是历史快照：Namespace UID `f37030f1-6b2e-4a6f-b779-45838b1c1cdd`、现有两个 Pod、三目标名空闲、Reader RBAC 符合预期，但 `kubectl top nodes` 无 Metrics API，未得出 request 余量。本节以下为 **Gate B0 本轮重新查询**，不借用旧 PASS。

## 本轮只读集群事实

查询仅通过现有 `ssh -o BatchMode=yes k8s-m` 执行只读 `kubectl`；未打印 kubeconfig、Token、完整 Pod Log、其他 Namespace 的资源名称或镜像。

| 门禁 | 本轮证据与判断 |
| --- | --- |
| 主机、context、API | SSH 主机 `k8s-master01`；`kubernetes-admin@kubernetes`；API `https://192.168.31.136:6443`；`/readyz=ok`。与 Gate A 记录一致。 |
| Namespace 身份 | `kube-triage-demo` UID `f37030f1-6b2e-4a6f-b779-45838b1c1cdd`，`app.kubernetes.io/part-of=kube-triage-agent`；与历史 UID 相同。 |
| 既有资源 | `triage-repair-demo` Deployment UID `5c908332-ddb3-4de1-9bc5-97cd34f62fdd`，项目标签正确，Desired/Ready=1/1；其唯一 Pod 为 Running/Ready，ReplicaSet owner 正确。`triage-sample` 为 Succeeded，项目标签正确，无 ownerReference。未改变二者。 |
| 名称冲突 | `triage-case-crashloop`、`triage-case-imagepull`、`triage-case-healthy` 在目标 Namespace 中全部不存在；这是查询时点事实，未来创建前必须重查。 |
| Reader RBAC | `kube-triage-reader` SA、Role、RoleBinding 均在目标 Namespace，带项目标签；SA `automountServiceAccountToken=false`，Role 仅 pods/events get,list 和 pods/log get，Binding 指向该 SA。以该 SA `auth can-i`：get/list pods、get pods/log、list events 为 yes；get secrets、create pods、update deployments/scale 为 no。此处只验证 RBAC 规则，**本轮未调用 Real MCP**。 |
| Namespace 策略 | `ResourceQuota=[]`、`LimitRange=[]`。只读范围内未见该两类配额阻断；不代表 Admission、镜像拉取或运行时一定成功。 |

### Node requests 余量

来源：`kubectl get nodes -o json` 的 Ready、unschedulable、Taints、Conditions、Allocatable；`kubectl describe nodes` 中每 Node 的 **Allocated resources / Requests** 汇总及 Non-terminated Pods 数。仅在私有查询进程中解析 describe，未展示其他 Namespace Pod 列表。CPU 换算为 millicore，内存用 `1 Mi=1024 Ki`；`1912452Ki=1867.63Mi`。剩余 = Allocatable − 已分配 Requests，Pod 名额 = Allocatable pods − 当前非终止 Pod 数。括号中的百分比是 kubectl 对 requests/limits 的显示，不是实际利用率。

| Node | 调度条件 | Allocatable CPU / Memory / Pods | 已分配 Requests CPU / Memory；Pod 数 | Request 层剩余 CPU / Memory；Pod 名额 |
| --- | --- | --- | --- | --- |
| `k8s-master01` | Ready，未 cordon；control-plane `NoSchedule` taint；三种 Pressure=False | 2000m / 1867.63Mi / 110 | 850m / 240Mi；12 | 1150m / 1627.63Mi；98；**默认不纳入本次普通 Pod 调度池** |
| `k8s-node01` | Ready，未 cordon；无 taint；三种 Pressure=False | 2000m / 1867.63Mi / 110 | 10m / 32Mi；5 | 1990m / 1835.63Mi；105 |
| `k8s-node02` | Ready，未 cordon；无 taint；三种 Pressure=False | 2000m / 1867.63Mi / 110 | 0m / 0Mi；3 | 2000m / 1867.63Mi；107 |

两个 worker 合计可调度分母为 4000m / 3735.26Mi / 220 Pods；当前 requests 为 10m / 32Mi，非终止 Pod 8 个；request 层剩余 3990m / 3703.26Mi / 212 Pod 名额。三份清单合计新增 requests **20m / 64Mi / 3 Pods**，limits **200m / 128Mi**；单个 worker 的 request 余量已可容纳全部三 Pod，也可以分散放置。若无并发变化且三 Pod 被调度到两个 worker，请求预算后的合计剩余为 3970m / 3639.26Mi / 209 名额。该算术只证明当前 requests 层的适配，不预测调度器选择、驱逐、实际内存峰值或镜像拉取。Limits 不用于此处 request 余量相减。

`kubectl top nodes --no-headers` 返回 `Metrics API not available`。**真实 CPU/内存利用率 = UNKNOWN**；Requests 并非物理空闲，Pressure=False 是该次 Node Condition 观测，不保证测试窗口内始终无压力。若未来 Node 汇总缺失、权限拒绝或明显压力，Gate B 应判 BLOCKED，不能据本表继续。

## 最终待人工审阅的 Manifest

本轮三份 YAML 与 `origin/main` 的本地 Git diff 为空，未调整安全限制。SHA256 由本 Worktree 的文件计算：

| 场景 / 精确 Pod 名 | SHA256 | Requests | Limits |
| --- | --- | --- | --- |
| `triage-case-crashloop` | `4af2da844f506955d8d4abcabd1b380a1528d5ec3952ef18a50d6df5c5269d1c` | 5m / 16Mi | 50m / 32Mi |
| `triage-case-imagepull` | `77f990e474bcf0940aed43e8693f2879b3aa6db59ad24c5b5df36f3fcf593c59` | 5m / 16Mi | 50m / 32Mi |
| `triage-case-healthy` | `1bcc6055af086c8cc8840a2804064dada63fc911264d042228748bf3c097381e` | 10m / 32Mi | 100m / 64Mi |

均为精确名称、单容器 Pod；固定目标 Namespace 与项目标签，`automountServiceAccountToken=false`、非 root UID 101、RuntimeDefault seccomp、drop ALL capabilities、禁止提权；无 hostPath、hostNetwork、hostPID/hostIPC、特权或宿主访问。CrashLoop 的配置缺失会触发重启和 Event 噪声；ImagePull 的刻意无效 tag 会触发镜像拉取重试和 Event 噪声；Healthy 的真实 Ready 仍需以后观察。测试窗口、镜像代理、Event 保留时间、节点瞬时压力、日志可见性及真实 Reader/LLM 归因仍未验证；不要为补历史 PASS 而制造新故障。

## 离线测试与验收矩阵

`uv sync --frozen --offline --python 3.13` 使用 Host 现有 Python 3.13.14 与 uv 缓存完成，无下载。工作目录 `server` 下执行 `uv run --frozen ruff check src tests ../scripts/check_issue11_manifests.py`、`uv run --frozen pytest -q`、`uv run --frozen python ../scripts/check_issue11_manifests.py`：分别 PASS、106 passed、PASS。测试包括正常三份、Namespace/标签/资源/镜像/hostNetwork/hostPath/提权负样本及 `python -O` 仍拒绝。CI 在依赖安装后运行相同的 ruff 与静态脚本。`git diff --check` 为 PASS。远端 CI 结果须以 Draft PR 实时检查为准。

独立 `codex review --uncommitted`：**BLOCKED**。sandbox 内运行时无法初始化；Host 执行被自动审批以“可能把未提交的私有代码和文档发送给 Codex 后端，缺少对该目的地的明确授权”拒绝。没有改道重试，也不把本地自查写成独立 Review PASS；需用户另行授权该外发审查后才能补结论。当前自查已核对脚本无 `assert`、CI 只增静态命令、YAML 无 diff、负样本可拒绝。

| 编号 | 状态 | 证据 / 边界 |
| --- | --- | --- |
| B0-01 实时仓库与独立 Worktree | PASS | Issue open，PR #17 merged，最新 main 与新分支基线一致。 |
| B0-02 集群/API/Namespace 身份 | PASS | SSH、context、API、readyz、UID 与项目标签实时核对。 |
| B0-03 既有资源归属及名称空闲 | PASS | Deployment 1/1、两个既有 Pod 归属；三个目标名不存在。 |
| B0-04 Reader 权限 | PASS | SA/Role/Binding 与 `can-i`；Real MCP 调用不在本项。 |
| B0-05 Node request 调度预算 | PASS | 两 worker requests 与 Pod 数有余量；Metrics 实际利用率 UNKNOWN。 |
| B0-06 Namespace 配额与明显压力 | PASS | Quota/LimitRange 为空；三 Node Ready，Pressure=False；Admission 未实测。 |
| B0-07 Manifest 完整性与安全 | PASS | 三份 SHA、精确字段、资源合计；YAML 无本轮 diff。 |
| B0-08 离线脚本、负样本、CI 补强 | PASS | 本地 ruff、106 tests、静态脚本通过；远端 CI 独立核对。 |
| 独立 Review | **BLOCKED** | Host `codex review` 被自动审批拒绝；没有独立审查结论。 |
| Gate B 真实 Kubernetes 创建/删除/回滚 | **BLOCKED** | 本轮没有用户写入授权，任何一次 create/delete/rollback 均不得执行。 |
| Real LLM + Real K8s diagnosis | **NOT RUN** | 未部署三案例，也未建立真实 Aegra Thread/Run；历史 Mock/Smoke 不能充当结果。 |

只读 B0 证据达到 **READY_FOR_AUTHORIZATION** 的前提判断：当前未见身份、名称、归属或 requests 冲突。该状态仅表示可提交下述精确授权草案，**绝非写入许可**；执行前必须重新核对实时身份、名称、请求余量、Manifest SHA 和测试窗口。

## 下一轮 Gate B 授权请求草案（未提交、未批准）

请用户届时单独审阅并明确批准：目标仅为 SSH alias `k8s-m` → `k8s-master01`，context `kubernetes-admin@kubernetes`，API `https://192.168.31.136:6443`，Namespace `kube-triage-demo` 当前 UID `f37030f1-6b2e-4a6f-b779-45838b1c1cdd`。未来写动作严格限于在该 Namespace **逐个创建**：

1. `Pod/triage-case-healthy`：只用 SHA256 `1bcc6055af086c8cc8840a2804064dada63fc911264d042228748bf3c097381e` 的 YAML。
2. `Pod/triage-case-crashloop`：只用 SHA256 `4af2da844f506955d8d4abcabd1b380a1528d5ec3952ef18a50d6df5c5269d1c` 的 YAML。
3. `Pod/triage-case-imagepull`：只用 SHA256 `77f990e474bcf0940aed43e8693f2879b3aa6db59ad24c5b5df36f3fcf593c59` 的 YAML。

每个动作前重查精确身份、目标名不存在及当时 Node 状态；创建后仅只读检查目标 Pod UID/状态和同 UID Event，再考虑下一项。任一身份/归属漂移、名称冲突、权限拒绝、压力、API 不可达、创建回执不明或预期外现象立即停止，不自动重试、覆盖、清理或回滚。总新增 requests 20m/64Mi，limits 200m/128Mi；CrashLoop 重启、ImagePull 拉取重试带来持续 Event/镜像请求噪声，测试窗口与影响由人审阅。此草案 **本轮没有批准**；所有创建、删除、回滚保持 **BLOCKED**。未来删除需要另一次独立明确授权，不能从创建授权推导。

## 60–90 秒面试讲述

“我先确认 GitHub main 已包含 Gate A 的合并，另建 Worktree；再只读验证 SSH 主机、Kubernetes context、API readyz 和 Namespace UID，没有把历史截图当作实时状态。三个待建 Pod 名都空着，Reader 的 RBAC 仅允许 Pod、Event 和 Log 读取，`can-i` 只证明授权规则，并不代表本轮调用过真实 MCP。资源判断用节点 Allocatable 减去已分配 Requests：两个 worker 对 20m CPU、64Mi 和三个 Pod 都有请求预算；control-plane 有 NoSchedule taint，不计入普通调度池。Metrics API 缺失，所以我只能说 request 层适配，不能说真实 CPU 或内存空闲。三份 Manifest 的 SHA 与安全字段固定，脚本改成显式异常，CI 和负样本能防止 `python -O` 跳过。真实集群写入仍需另一次精确授权，旧 Phase 3A 的 Mock 分数不能冒充真实诊断；为了补一个 PASS，我不会擅自制造故障或清理资源。”
