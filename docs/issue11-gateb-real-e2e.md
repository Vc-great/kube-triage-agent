# Issue #11 · Gate B1 实时只读预检与 Gate B2 授权边界

日期：2026-10-13（北京时间）。本页记录一次新的 B1 只读观察和离线准备；**没有 Kubernetes 写入授权**。Issue #11 保持 open，PR #17/#18 均已 merged。Git `origin/main` 与本工作树基线为 `d07290dbd1a9541279ab2f21436bb1993ea7f620`，分支 `codex/issue11-gateb-real-e2e`。本页不修改 Phase 3A/3B 历史结论；B06=FAIL 与 PR #18 独立 Review=BLOCKED 保留。

## B1-01 · 清单与代码

本轮复核了 README、Issue #11 的 Scenario/Gate A/B0 文档、CI、三份 YAML、离线 Manifest 检查脚本、Graph/LLM/Prompt/MCP Client/Repair、两份 acceptance、旧 Phase 3A 评测与报告。正式诊断仍是单 LangGraph、Aegra Thread/Run/SSE/Checkpoint、四个原生只读 Reader 工具；Graph 限每轮 4 次模型决策与 6 次工具调用，Repair 独立且默认关闭。`scripts/eval_phase3a.py` 的 static-fixture/Mock 判据不得用于本次真实案例。Graph SHA256：`f3ba127062d7a1b93b1e566bde942eac68f5391c75b0d24e77a6805d932c4fb3`。

| 顺序 / Pod 名 | 精确文件 | 本轮 SHA256 | requests / limits |
| --- | --- | --- | --- |
| 1 `triage-case-healthy` | `infra/k8s/scenarios/triage-case-healthy.yaml` | `1bcc6055af086c8cc8840a2804064dada63fc911264d042228748bf3c097381e` | 10m / 32Mi；100m / 64Mi |
| 2 `triage-case-crashloop` | `infra/k8s/scenarios/triage-case-crashloop.yaml` | `4af2da844f506955d8d4abcabd1b380a1528d5ec3952ef18a50d6df5c5269d1c` | 5m / 16Mi；50m / 32Mi |
| 3 `triage-case-imagepull` | `infra/k8s/scenarios/triage-case-imagepull.yaml` | `77f990e474bcf0940aed43e8693f2879b3aa6db59ad24c5b5df36f3fcf593c59` | 5m / 16Mi；50m / 32Mi |

三份文件字节与提示词预期一致，无本轮 Diff。单文档、固定 Namespace/标签、单个非特权容器、非 root UID 101、`automountServiceAccountToken=false`、`RuntimeDefault` seccomp、drop ALL capabilities、禁止提权；无 hostPath、hostNetwork、hostPID、hostIPC。请求与限制未增大，CrashLoop 与 ImagePull 诱因未变。离线 Manifest 脚本及测试结果见下方矩阵；任何后续字节变化均使本授权草案失效。

离线复核：Host 已有 Python 3.13.14 与 uv 0.11.21；`uv sync --frozen --offline --python 3.13` 仅复用缓存建本工作树的 `.venv`，未下载。`scripts/check_issue11_manifests.py` PASS；Ruff PASS；pytest **106 passed**；`git diff --check` PASS。Ruff 缓存放在 `/private/tmp/issue11-gateb1-ruff`，pytest 禁用缓存。此前沙箱内 Ruff 默认缓存权限失败、一次 pytest 路径输入错误，修正命令后上述检查通过；没有将失败尝试算为测试通过。

## B1-02 · 本轮只读集群快照（公开摘要）

2026-10-13 17:30–17:35 CST，通过既有 SSH alias 执行了只读查询。Host、context、API `/readyz`、目标 Namespace UID 与项目标签均与预期一致。既有演示 Deployment 的归属和 Desired/Ready=1/1、对照 Pod 的归属均已复核。三次按精确名称 `get pod --ignore-not-found -o name` 均返回空，目标 Namespace 的 ResourceQuota/LimitRange 列表也为空。**内部地址、身份 UID 与节点资源明细只保存在本地受限 `.local/issue11-real-e2e/b1-full-report.md`，不进入公开 PR。**以上是查询时点状态，执行前仍须重查。

Reader SA/Role/RoleBinding 的项目标签与绑定对象正确；Role 仅允许 pods/events get,list 与 pods/log get。以该 SA 做 `kubectl auth can-i`：get/list pods、get pods/log、list events 均 yes；get secrets、create pods、update deployments/scale 均 no。

本轮 `kubectl get nodes -o json` 与 `kubectl describe node` 显示两台 worker 均 Ready、未 cordon、无 taint，Memory/Disk/PIDPressure=False；control-plane 的 NoSchedule 节点未计入普通 Pod 调度池。**每台 worker 单独**都有足够 requests 余量容纳三个新 Pod 合计 **20m / 64Mi / 3 Pod**，limits 合计 **200m / 128Mi**。这不是实际利用率或 Admission 保证。`kubectl top nodes` 报 `Metrics API not available`，实际 CPU/内存利用率 **UNKNOWN**。本轮 Warning Event 汇总为 0；不能据此保证测试时无噪声。每节点精确数值在上述私有报告与本次用户授权请求中提供。

## B1-03 · Runtime 与费用

既有正式 API 健康，真实模型配置与 API Token 均存在，Reader URL 指向项目内部服务，`REPAIR_ENABLED=false`、`REPAIR_SIMULATED=false`。其容器内实际发现四个原生 Reader 工具，一次针对既有对照 Pod 的 `pods_get` 返回 `ok=true`，未见 static-fixture 标识。这证明一次只读 Reader 通路，**没有测试模型可用性或三个场景**。

独立 Mac development API 的 `.local/dev/state.json` 报 `full/failed` 且进程不在运行；本轮 12026/18080 没有本地 listener。既有私有开发环境文件权限为 0600，配置了真实模型名、模型 Key、独立 API Token、development 数据库、Reader 回环地址、Repair=false；文件内容和密钥没有输出。当前无适合新 Thread 的**已运行且已验证** development API，因此 B1-03=BLOCKED。后续方案是先核对开发数据库/Redis/Reader 隧道与端口归属，再单独启动或修复 development 运行态，验证独立认证、四工具真实读取及模型服务；不得重启/重建 dev01 稳定 Compose 项目或把正式数据库用于新演练 Thread。该运行态准备不属于本次 Kubernetes create 授权。

每条 Run 最多 4 次模型决策、6 次 Reader 调用，三条最多 12 次模型决策、18 次工具调用；`ChatOpenAI(max_retries=1)` 可能带来最多 24 次模型请求尝试。代码未设单次输入/输出 Token 硬上限，模型服务计价及余额本轮未验证，所以**无法给出可信人民币费用上限**。付费模型调用前还需用户确认可接受的费用上限及停止策略；当前 Real LLM E2E=NOT RUN。

## B1-04 · 离线协议与人工核对契约

三个中性提问，分别在新 Thread/Run 使用，不提示设计诱因：

1. `请只读调查 kube-triage-demo 中的 triage-case-healthy：说明目前 Pod 状态、关键证据、不能确认的事项以及人工建议。`
2. `请只读调查 kube-triage-demo 中的 triage-case-crashloop：说明异常现象、可核实的原因、尚缺的证据与人工建议。`
3. `请只读调查 kube-triage-demo 中的 triage-case-imagepull：根据 Pod 与相关事件分析失败现象和原因确定性，说明无日志时的限制。`

只复用现有 `POST /threads` → `POST /threads/{id}/runs/stream` → `GET /threads/{id}/state`、`history`、`runs` 的协议和现有 `agent` assistant。三个场景必须各用一个新 Thread；只有 B2 授权、Pod 确认存在且 development API/Reader/模型可用、费用边界明确后才发起 Run。原始 State、History、SSE、Pod Log 与 Event 全文仅存被 Git 忽略的 `.local/issue11-real-e2e/`（目录 0700、文件 0600）；公开报告仅写脱敏短摘录。每案预留 `manifest_sha256 / pod_uid / model_name / api_mode / graph_sha / thread_id / run_id / tool_call_id / tool_message_id / event_uid / final_answer_excerpt / human_review / status`，未知填 `UNKNOWN`，未运行填 `NOT RUN`，绝不虚构 ID。

人工检查顺序：先核实 manifest hash 和实际 Pod namespace/name/UID；检查 SSE `end` 且无未解释 `error`、Run status、State/History；按 `AIMessage.tool_calls[].id` 与 `ToolMessage.tool_call_id` 一一配对并核实该工具的 namespace/name 参数与本目标一致；解析 Reader 的 `ok/result` 和原生 YAML，确认 Pod metadata UID 及 Event `involvedObject.kind/namespace/name/uid` 匹配；再核对诊断短摘录。UID 缺失的 Event 只能作弱线索，不足以做强归因。没有要求四工具全部成功；工具失败必须报告。检查模型是否越过 4 决策/6 Tool Call、是否把其它 Pod Warning 归于 Healthy、是否把设计时 `REQUIRED_GREETING` 当作已观察日志、是否从 ImagePullBackOff 猜认证/DNS/tag 子原因。Ground Truth 同时引用设计预期与真实 Pod/Event/Log 观测；Diagnosis label、Evidence Grounding 0–2、误报、因果越界、日志限制与工具失败均由独立人工判定 `PASS/FAIL/UNKNOWN`，不得让程序或模型自评为正确。

## Gate 与停止点

| Gate | 状态 | 判定 |
| --- | --- | --- |
| B1-01 最新 main、三 YAML SHA、代码静态一致 | PASS | 本轮 hash 与文件/代码核对；离线测试单列。 |
| B1-02 真 K8s 只读身份、名称、RBAC、每节点预算 | PASS | 本轮查询满足请求层条件；Metrics 实际利用率 UNKNOWN。 |
| B1-03 Real 模型 + Real Reader 的独立运行态 | **BLOCKED** | 正式 Reader 可读，但独立 development API 未运行；模型服务和费用未验证。 |
| B1-04 三案离线数据契约 | PASS | 中性提问、关联/人工核对规则已定义；真实案例没有执行。 |
| B1-05 精确授权请求并停止 | PASS | 交付时向用户展示精确参数并等待真人决定；这不代表 B2 已获批准。 |
| B2-01 用户明确批准 | **BLOCKED** | 本提示词和旧授权均不算本次批准。 |
| B2-02 三 Pod 创建/UID/Event | NOT RUN | 没有 Kubernetes 写入。 |
| B2-03 三条 Real LLM + Real MCP Run | NOT RUN | 无新 Thread/Run。 |
| B2-04 独立人工诊断核对 | NOT RUN | 无真实诊断结果。 |
| B2-05 最终 Pod 状态/保留边界 | NOT RUN | 三目标 Pod 尚不存在。 |

在进入 B2 前必须重查 Host/context/API/Namespace UID、三份文件 SHA、所有目标名、Reader 身份、worker 压力与请求层余量、Quota/Admission 相关可见条件。任一漂移、同名对象、未知 create 回执、Reader/模型身份不明、费用未获同意都停止后续写入。精确 create 仅允许 Healthy → CrashLoop → ImagePull 各一次；不自动重试、删除、回滚、修改 RBAC、启用 Repair 或操作其它 Namespace。创建之后的清理另按每个实际 name/UID 申请授权；若无授权，Healthy 可能持续运行，CrashLoop 和 ImagePull 会持续重启/拉取重试并产生 Event/Registry 噪声。
