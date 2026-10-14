# Issue #11 Gate B2 后续只读复核（2026-10-14，北京时间）

本页接续 [Gate B2 历史补记](issue11-gateb2-final-report.md)，只记录新的观察时点。基线为 `origin/main=0385a1cf01fdee8e59ca1061731d9130b6245e0f`；PR #21 已合并，Issue #11 仍 open。用户在本轮精确授权后，Kubernetes `create` **恰好一次且成功**；新模型 Thread/Run **0 次**。

## Healthy 重启与节点证据

2026-10-14 08:42:21 与 08:42:53（北京时间）的两次只读快照中，Healthy 保持同一 UID、Running、Pod/Container Ready，重启数均为 1；容器最后一次终止的 `reason=Unknown`，并非应用根因。两个快照中共同 Node 均 Ready、无 Memory/Disk/PID Pressure、无 taint 或 cordon。Healthy 与 CrashLoop 在同一历史时刻各有一次同 UID 的 `SandboxChanged`，没有观察到新计数。

补充的 Node Event 直接记录了当时的 `Rebooted`、短暂 `NodeNotReady` 和恢复 `NodeReady`。这支持将两 Pod 同时受影响与节点重启联系起来；**节点为何重启仍 UNKNOWN**，也不能把 `Unknown` 退出解释成 Healthy 应用缺陷。两次快照只证明当前短窗口稳定，不保证后续持续稳定。历史 Healthy Run 的重启 0、Ready 和无误报判断只适用于模型当时可见的 ToolMessage。

CrashLoop 保持原 UID、Ready=False，复核时容器 `Waiting.reason=CrashLoopBackOff`、上次退出码 42，重启继续增长；同 UID BackOff Event 仍可见。这是新时点的只读事实，不追改历史严格 Gate=FAIL，也不回填到旧 Run 的 ToolMessage。

## development Runtime 与创建前检查

从上述 main 提交的独立私有工作树，经官方 `make dev` 启动一次 `full/ready` development supervisor。启动前确认旧 supervisor 已停止、目标本地端口空闲、私有配置权限与隔离身份正确。启动后 `/health=200`、匿名请求被 401 拒绝、开发 Token 的只读请求成功；开发 Postgres 的 database/user 均为专用开发身份，Redis PING 成功。Real Reader 只发现四个原生只读工具，一次针对现存 Healthy 的 `pods_get` 成功并匹配目标 UID。Graph、LLM、Prompt、Reader 代码来自该 main 提交；未调用 LLM。`gpt-6-luna` 的 Responses API 与 High 仅为请求配置，服务端实际 effort **UNKNOWN**。

ImagePull 清单 SHA256 为 `77f990e474bcf0940aed43e8693f2879b3aa6db59ad24c5b5df36f3fcf593c59`，离线清单校验通过；执行前目标名称不存在。Reader SA/Role/Binding 只允许所需 Pod/Event/Log 读取；`create pods`、`get secrets`、`update deployments/scale` 均被拒。目标 Namespace 无 ResourceQuota/LimitRange；两台 worker Ready、无压力或调度禁用，请求与 Pod 槽位足够容纳单个 5m CPU / 16Mi Pod。可见 Admission 策略清单为空。Metrics API 不可用，实际 CPU/内存占用 **UNKNOWN**。在用户回复“批准”后，再次核对目标、集群身份、运行态、清单 SHA 和调度预算，才发出唯一一次 `kubectl create`；私有记录保存了时间、命令意图和成功回执。

创建后只读观察到新 Pod `Pending`、容器先为 `ErrImagePull`，随后为 `ImagePullBackOff`，Ready=False、重启 0。同一对象 UID 的 `Pulling`、`Failed`、`BackOff` Event 和容器等待消息显示该镜像解析返回 `NotFound`；本轮没有据此猜测认证或 DNS 故障。目标镜像未启动，容器日志不可用不改变拉取失败的判据。获批范围不包含删除、重建或重试；Pod 保留并继续发起拉取重试。

尝试启动一次真实 Luna + Real Reader 诊断前，自动审批审查拒绝了动作：现有批准被认定仅覆盖 Kubernetes create，未明确覆盖将 Pod 观测数据发送至真实模型的具体调用。**命令未执行，Thread/Run 均未创建，未发生模型数据外发。** 不通过其他通道绕过该拒绝；真实诊断须另获明确授权。

## 本轮状态与资源

| Gate | 状态 | 说明 |
| --- | --- | --- |
| U0 基线与代码身份 | PASS | 已 fetch；PR #21 合并，Issue #11 open，运行代码与 main 一致。 |
| U1 Healthy 现状 | PASS | 两次有界快照 Ready、重启数不变；节点重启为历史 Event，触发原因未知。 |
| U2 CrashLoop 分层 | PASS | 当前 Waiting/退出码/BackOff 与历史严格 FAIL、旧模型证据分开。 |
| U3 development Runtime | PASS | full/ready，开发 DB/Redis 与四只读 Reader 已验证；未调模型。 |
| U4 ImagePull 只读预检 | PASS | 精确清单、名称空闲、RBAC、声明请求预算已核对；实际利用率未知。 |
| U5 单次 create 授权 | PASS | 用户本轮对前述精确 create 请求回复“批准”。 |
| U6 唯一 create | PASS | 尝试数 1、回执成功，实际对象 UID 已在私有证据核对。 |
| U7 ImagePull 目标证据 | PASS | 同 UID 的等待状态、Failed/BackOff Event 支持镜像解析 `NotFound`。 |
| U8 Real Luna + Reader Run | BLOCKED | 自动审批审查拒绝模型数据外发；命令未执行，新 Thread/Run 数 0。 |
| U9 真人独立评分 | NOT RUN | H/C 评分 PENDING；I 无 Run，不计准确率。 |
| U10 归档与评审 | BLOCKED | 私有证据已保存，Draft PR 的 Python/Web/Compose CI 通过；独立 Review、真人评分与模型调用授权仍待完成。 |

最终只读资源状态：Healthy **EXISTS** 且 Ready，继续运行；CrashLoop **EXISTS** 且持续重启，继续产生 Event；ImagePull **EXISTS** 且等待 `ImagePullBackOff`，继续拉取重试并产生 Event。本轮未删除或清理任何资源。今后若要清理，须先按届时实际对象 UID、动作和影响另行批准，不能把创建许可当成删除许可。历史首次 M1=FAIL、B06=FAIL、PR #18 Host Review=BLOCKED 及 Phase 3A Mock 分数保持原结论，不计作本次真实诊断准确率。

原始只读快照、Node Event、create 回执与运行态摘要保存在 Git 忽略的私有受限目录；公开文档仅保留脱敏事实。下一步需先由真人明确批准这一次真实模型诊断的数据外发范围，再核对运行态并发起最多一个新 Thread/Run。当前不建议人工关闭 Issue #11。
