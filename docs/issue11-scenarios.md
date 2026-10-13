# Issue #11 · Gate A：真实故障 Scenario 草案

本页对应 [Issue #11](https://github.com/Vc-great/kube-triage-agent/issues/11)，只定义三个未来可能在 `k8s-m` / `kube-triage-demo` 使用的独立 Pod。三个 YAML 均为**未部署草案**。Gate A 不申请 Kubernetes 写权限，也不执行清理。基线 `origin/main`：`9e79cb9a75fd4c6b015e11f06cb5ff40a3753b55`。

## 与现有实现的关系

- 当前正式路径为真 LLM → 四个原生只读 Reader MCP 工具 → Kubernetes API；`/repair-demo` 是独立固定 HITL 路径，默认关闭。本草案不变更二者，也不改变 `triage-repair-demo`、`triage-sample`、RBAC、Token、Phase 3A Golden 或历史评分。
- Reader 只有 `pods_list_in_namespace`、`pods_get`、`events_list`、`pods_log`。`pods_log` 的参数只允许 `namespace/name/tail/container`，没有 `previous`。CrashLoop 的上一次实例日志可能不可得；在这种情况下只能根据 Pod 状态、终止码和目标 Event 描述现象，应用错误若无日志就必须标为证据不足。
- 历史 `scripts/eval_phase3a.py` 要求 `mock=true` 和 `source=static-fixture`，并假设 JSON 结构与按名称过滤 Event；不能直接用于真实 Reader 的 YAML 输出及目标 UID 校验。`scripts/acceptance.py` 是真实链路 smoke，不是三类故障准确率评测。本期只制定独立解析契约，不改历史 Runner。
- `busybox:1.36.1`、非 root UID 101、`httpd -f -p 8080` 和 HTTP readiness 与现有 `repair-demo.yaml` 相同；2026-10-13 只读观察其现有 Pod 为 Running/Ready。新 Healthy Pod 的实际可用性仍须 Gate B 后核对。

## 三个隔离 Pod

| 场景 | 声明式文件 | 可复核诱因和预计状态 | 证据与结论边界 |
| --- | --- | --- | --- |
| CrashLoop | `infra/k8s/scenarios/triage-case-crashloop.yaml` | `REQUIRED_GREETING` 故意未声明；shell 输出固定错误后 `exit 42`，`restartPolicy: Always`。预计先有 terminated/exitCode=42 和 restartCount 增长，再可能出现 waiting.reason=`CrashLoopBackOff`。 | 目标 Pod 的 `containerStatuses`、`lastState.terminated`、目标 UID 的 BackOff Event；`pods_log` 若可见固定错误，才能引用“缺少必需配置”。无日志或终止记录时不能将源码设计当成真实运行证据。 |
| ImagePull | `infra/k8s/scenarios/triage-case-imagepull.yaml` | `busybox:triage-issue11-tag-does-not-exist-20261013` 和 `imagePullPolicy: Always`。预计 Pending、ErrImagePull/ImagePullBackOff、restartCount=0。 | 仅真实目标 UID 的 Failed/Pulling/BackOff Event 可确认具体拉取失败原因。Tag 名表达设计意图，不证明远端返回 tag 缺失；认证、DNS、镜像代理和仓库错误必须由 Event 区分。容器未启动时无运行日志是预期，不是模型故障。 |
| Healthy | `infra/k8s/scenarios/triage-case-healthy.yaml` | `busybox:1.36.1` 在 8080 持续运行 `httpd`，HTTP `/` readiness。预计 Running 且 Ready=true。 | `pods_get` 的 phase、容器 ready 和重启数，加目标 UID 的 Event。Namespace 内其他 Pod 的 Warning 只能作为噪声，不能归于 Healthy；若没有这种噪声，不制造。 |

三个 Pod 均固定 Namespace，带 `app.kubernetes.io/part-of=kube-triage-agent` 和独立 component 标签；`automountServiceAccountToken: false`、UID 101 非 root、RuntimeDefault seccomp、drop ALL capabilities、禁止提权。每个只有一个容器；无 Service、Secret、持久化卷、hostPath、hostNetwork、hostPID、hostIPC 或 NodePort。合计 requests 为 20m CPU / 64Mi 内存，limits 为 200m CPU / 128Mi 内存；这是清单上限，不等于节点实时余量。CrashLoop 反复重启和 ImagePull 重试会生成有限但持续的 kubelet/Event 噪声，故 Gate B 仍需人工评估影响。

## 真实证据与隔离数据集契约（Gate B 才采集）

每个场景使用新的 Aegra Thread/Run 和中性中文提问；保存代码 SHA、模型标识、场景文件 hash、问题、目标 Namespace/名称、**实际观察后**记录的 Pod UID、Run 状态、Tool Call ↔ ToolMessage ID、四工具调用结果类型、脱敏最终回答及人工评分。Pod UID 不在 Gate A 虚构。原始 Pod Log、Token、kubeconfig、Key 不入库；只保留足以审查的短摘录和来源 ID，私有证据目录权限受限。

解析真实 Reader 时，先按 MCP `ok`/错误与原生 YAML 文本解析，再确认目标 `metadata.namespace/name/uid`。Event 仅当 `involvedObject.kind=Pod`、`namespace/name/uid` **同时匹配目标**才算目标证据；UID 缺失、名称重复或 Event 归属异常都不能用于根因断言，应停止该案例并人工核实。JSON Fixture 的 `mock/source` 字段不可作为真实证据。每次判断区分观察到的状态、推断原因及未确认事项；人工审核 Ground Truth 与 Grounding，不把模型答案自评为正确。

## Gate B 前置检查与授权边界

1. 再次只读确认 SSH 目标、context、API Server、Namespace UID/归属标签、三个名称空闲、现有稳定资源 UID/状态，以及 Reader 身份、四工具与最小 RBAC。若任何一项变化、已有同名 Pod、标签/UID 异常，停止该场景。
2. 重新证明调度资源余量。2026-10-13 `kubectl top nodes` 返回 `Metrics API not available`；只看到三个 Ready 节点各有 2 CPU / 1912452Ki allocatable，**实时余量未知**。没有替代证据前 Gate B 保持 BLOCKED。目标 Namespace 当时无 ResourceQuota/LimitRange。
3. 用户下一轮需对**精确动作**另行授权：在 `k8s-m`（当前 context `kubernetes-admin@kubernetes`、API `https://192.168.31.136:6443`）、仅 `kube-triage-demo`，针对上述三个确认为空闲的 Pod 名，审阅三份 YAML 的最终 Diff 后分别创建。原状为 2026-10-13 只读快照中三名均不存在；此状态必须执行前重查。预计增加上述 requests/limits、重启/拉取 Event 及少量日志；镜像代理、节点资源、日志可见性与误归因仍有风险。
4. 回退与后续删除是**另一次授权**：仅在记录实际 UID 并重新核对对象仍属本项目后，提交精确 Pod 名/UID/动作及影响供用户决定；不自动删除、重建、scale 或重置 Namespace。Repair Demo 与稳定项目不在操作范围。

**面试追问：** 为什么 `ImagePullBackOff` 加上一个看似不存在的 tag 仍不能断言“tag 不存在”？因为运行态可能受到镜像代理、认证、DNS 或 Registry 响应影响；需把目标 Pod UID 的 Event 原文与容器 waiting 状态关联，再说明可以证实的层级。
