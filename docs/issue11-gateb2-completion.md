# Issue #11 Gate B2 后续只读复核（2026-10-14，北京时间）

本页接续 [Gate B2 历史补记](issue11-gateb2-final-report.md)，只记录新的观察时点。基线为 `origin/main=0385a1cf01fdee8e59ca1061731d9130b6245e0f`；PR #21 已合并，Issue #11 仍 open。用户在本轮精确授权后，Kubernetes `create` **恰好一次且成功**；另获模型数据发送授权后，ImagePull 的新 development Thread/Run **各一次**。

## Healthy 重启与节点证据

2026-10-14 08:42:21 与 08:42:53（北京时间）的两次只读快照中，Healthy 保持同一 UID、Running、Pod/Container Ready，重启数均为 1；容器最后一次终止的 `reason=Unknown`，并非应用根因。两个快照中共同 Node 均 Ready、无 Memory/Disk/PID Pressure、无 taint 或 cordon。Healthy 与 CrashLoop 在同一历史时刻各有一次同 UID 的 `SandboxChanged`，没有观察到新计数。

补充的 Node Event 直接记录了当时的 `Rebooted`、短暂 `NodeNotReady` 和恢复 `NodeReady`。这支持将两 Pod 同时受影响与节点重启联系起来；**节点为何重启仍 UNKNOWN**，也不能把 `Unknown` 退出解释成 Healthy 应用缺陷。两次快照只证明当前短窗口稳定，不保证后续持续稳定。历史 Healthy Run 的重启 0、Ready 和无误报判断只适用于模型当时可见的 ToolMessage。

CrashLoop 保持原 UID、Ready=False，复核时容器 `Waiting.reason=CrashLoopBackOff`、上次退出码 42，重启继续增长；同 UID BackOff Event 仍可见。这是新时点的只读事实，不追改历史严格 Gate=FAIL，也不回填到旧 Run 的 ToolMessage。

## development Runtime 与创建前检查

从上述 main 提交的独立私有工作树，经官方 `make dev` 启动一次 `full/ready` development supervisor。启动前确认旧 supervisor 已停止、目标本地端口空闲、私有配置权限与隔离身份正确。启动后 `/health=200`、匿名请求被 401 拒绝、开发 Token 的只读请求成功；开发 Postgres 的 database/user 均为专用开发身份，Redis PING 成功。Real Reader 只发现四个原生只读工具，一次针对现存 Healthy 的 `pods_get` 成功并匹配目标 UID。Graph、LLM、Prompt、Reader 代码来自该 main 提交。`gpt-6-luna` 的 Responses API 与 High 为请求配置；Run 的 Provider 元数据回显了模型名及 `response` 对象，未回显实际 effort，因此服务端 effort **UNKNOWN**。

ImagePull 清单 SHA256 为 `77f990e474bcf0940aed43e8693f2879b3aa6db59ad24c5b5df36f3fcf593c59`，离线清单校验通过；执行前目标名称不存在。Reader SA/Role/Binding 只允许所需 Pod/Event/Log 读取；`create pods`、`get secrets`、`update deployments/scale` 均被拒。目标 Namespace 无 ResourceQuota/LimitRange；两台 worker Ready、无压力或调度禁用，请求与 Pod 槽位足够容纳单个 5m CPU / 16Mi Pod。可见 Admission 策略清单为空。Metrics API 不可用，实际 CPU/内存占用 **UNKNOWN**。在用户回复“批准”后，再次核对目标、集群身份、运行态、清单 SHA 和调度预算，才发出唯一一次 `kubectl create`；私有记录保存了时间、命令意图和成功回执。

创建后只读观察到新 Pod `Pending`、容器先为 `ErrImagePull`，随后为 `ImagePullBackOff`，Ready=False、重启 0。同一对象 UID 的 `Pulling`、`Failed`、`BackOff` Event 和容器等待消息显示该镜像解析返回 `NotFound`；本轮没有据此猜测认证或 DNS 故障。目标镜像未启动，容器日志不可用不改变拉取失败的判据。获批范围不包含删除、重建或重试；Pod 保留并继续发起拉取重试。

首次尝试启动真实 Luna + Real Reader 诊断前，自动审批审查拒绝了动作：当时批准仅覆盖 Kubernetes create，未明确覆盖将 Pod 观测数据发送至真实模型。该命令未执行。用户随后**另行明确批准**模型数据发送及单次 Run；在重新核对 Runtime 和目标 UID 后，新建恰好一个 Thread、一个 Run，不补发第二次。

该 Run 的状态为 success、SSE 正常 end、State 无待续节点；三次模型决策、三个 Tool Call 均与唯一同 ID ToolMessage 配对，参数合法且 `ok=true`，没有 Repair 调用。工具轨迹为 `pods_list_in_namespace`、目标 `pods_get`、`events_list`；列表结果虽截断，但包含目标，目标 `pods_get` 未截断且直接给出当前 `ImagePullBackOff` 和镜像解析 `NotFound`。模型最终回答区分了观察到的拉取失败与未确认的标签写错、仓库发布、认证等子原因，未执行修复。它没有调用 `pods_log`；“容器未启动，缺少应用行为日志”是基于状态的解释，非工具返回的日志错误。

**Event 归属限制：** Reader 的 `events_list` 返回目标名称及 `Scheduled`、`Pulling`、`Failed`、`BackOff` 文本，也包含其他 Pod 的 Event，但未返回 `involvedObject.uid`；这些目标名称匹配的 Event 只能作弱证据。管理员独立只读回查核实了同 UID Event，不能回填为模型当时看见的 UID。模型回答引用了 Event，却没有提示这一归属缺口；核心 `NotFound` 判断仍有目标 `pods_get` 的直接状态消息支撑。最终 Grounding 和因果边界留给真人独立评分，不把 Run success 等同于诊断正确率。模型消息合计 Token Usage 为输入 15,677、输出 753；私有原始 SSE、State、History、Call/Message ID 和人工复核表均未进入公开 PR。

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
| U8 Real Luna + Reader Run | PASS | 另获授权后一个 Thread/Run；三次合法、成功且配对的真实工具调用，核心 Pod 证据充分；Event UID 缺失单列。 |
| U9 真人独立评分 | BLOCKED | H/C/I 的正确性、Grounding、误报与因果越界均 PENDING，不计准确率。 |
| U10 归档与评审 | BLOCKED | 私有证据与真人审阅表已保存；Draft PR 的 CI 和独立 Review 须按最新提交再核，真人评分及合并决定待完成。 |

最终只读资源状态：Healthy **EXISTS** 且 Ready，继续运行；CrashLoop **EXISTS** 且持续重启，继续产生 Event；ImagePull **EXISTS** 且等待 `ImagePullBackOff`，继续拉取重试并产生 Event。本轮未删除或清理任何资源。今后若要清理，须先按届时实际对象 UID、动作和影响另行批准，不能把创建许可当成删除许可。历史首次 M1=FAIL、B06=FAIL、PR #18 Host Review=BLOCKED 及 Phase 3A Mock 分数保持原结论，不计作本次真实诊断准确率。

原始只读快照、Node Event、create 回执、SSE/State/History 与人工审阅表保存在 Git 忽略的私有受限目录；公开文档仅保留脱敏事实。下一步请真人按项目原评分定义分别审阅 H/C/I，特别核对 ImagePull Event 缺 UID 时模型表述是否越界。清理、合并 PR 或关闭 Issue #11 均未获本轮授权，也不以 CI 代替真人评分。
