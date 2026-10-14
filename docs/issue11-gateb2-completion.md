# Issue #11 Gate B2 后续只读复核（2026-10-14，北京时间）

本页接续 [Gate B2 历史补记](issue11-gateb2-final-report.md)，只记录新的观察时点。基线为 `origin/main=0385a1cf01fdee8e59ca1061731d9130b6245e0f`；PR #21 已合并，Issue #11 仍 open。本轮 Kubernetes 写入 **0 次**、新模型 Thread/Run **0 次**，ImagePull 创建 **未获本轮授权**。

## Healthy 重启与节点证据

2026-10-14 08:42:21 与 08:42:53（北京时间）的两次只读快照中，Healthy 保持同一 UID、Running、Pod/Container Ready，重启数均为 1；容器最后一次终止的 `reason=Unknown`，并非应用根因。两个快照中共同 Node 均 Ready、无 Memory/Disk/PID Pressure、无 taint 或 cordon。Healthy 与 CrashLoop 在同一历史时刻各有一次同 UID 的 `SandboxChanged`，没有观察到新计数。

补充的 Node Event 直接记录了当时的 `Rebooted`、短暂 `NodeNotReady` 和恢复 `NodeReady`。这支持将两 Pod 同时受影响与节点重启联系起来；**节点为何重启仍 UNKNOWN**，也不能把 `Unknown` 退出解释成 Healthy 应用缺陷。两次快照只证明当前短窗口稳定，不保证后续持续稳定。历史 Healthy Run 的重启 0、Ready 和无误报判断只适用于模型当时可见的 ToolMessage。

CrashLoop 保持原 UID、Ready=False，复核时容器 `Waiting.reason=CrashLoopBackOff`、上次退出码 42，重启继续增长；同 UID BackOff Event 仍可见。这是新时点的只读事实，不追改历史严格 Gate=FAIL，也不回填到旧 Run 的 ToolMessage。

## development Runtime 与创建前检查

从上述 main 提交的独立私有工作树，经官方 `make dev` 启动一次 `full/ready` development supervisor。启动前确认旧 supervisor 已停止、目标本地端口空闲、私有配置权限与隔离身份正确。启动后 `/health=200`、匿名请求被 401 拒绝、开发 Token 的只读请求成功；开发 Postgres 的 database/user 均为专用开发身份，Redis PING 成功。Real Reader 只发现四个原生只读工具，一次针对现存 Healthy 的 `pods_get` 成功并匹配目标 UID。Graph、LLM、Prompt、Reader 代码来自该 main 提交；未调用 LLM。`gpt-6-luna` 的 Responses API 与 High 仅为请求配置，服务端实际 effort **UNKNOWN**。

ImagePull 清单 SHA256 为 `77f990e474bcf0940aed43e8693f2879b3aa6db59ad24c5b5df36f3fcf593c59`，离线清单校验通过，目标名称在最终只读快照中不存在。Reader SA/Role/Binding 只允许所需 Pod/Event/Log 读取；`create pods`、`get secrets`、`update deployments/scale` 均被拒。目标 Namespace 无 ResourceQuota/LimitRange；两台 worker Ready、无压力或调度禁用，请求与 Pod 槽位足够容纳单个 5m CPU / 16Mi Pod。可见 Admission 策略清单为空；实际创建结果仍不能由预检保证。Metrics API 不可用，实际 CPU/内存占用 **UNKNOWN**。所有这些只读结果都有时间边界，若日后获批创建，必须重新核对身份、运行态与预算。

## 本轮状态与资源

| Gate | 状态 | 说明 |
| --- | --- | --- |
| U0 基线与代码身份 | PASS | 已 fetch；PR #21 合并，Issue #11 open，运行代码与 main 一致。 |
| U1 Healthy 现状 | PASS | 两次有界快照 Ready、重启数不变；节点重启为历史 Event，触发原因未知。 |
| U2 CrashLoop 分层 | PASS | 当前 Waiting/退出码/BackOff 与历史严格 FAIL、旧模型证据分开。 |
| U3 development Runtime | PASS | full/ready，开发 DB/Redis 与四只读 Reader 已验证；未调模型。 |
| U4 ImagePull 只读预检 | PASS | 精确清单、名称空闲、RBAC、声明请求预算已核对；实际利用率未知。 |
| U5 单次 create 授权 | BLOCKED | 本轮未获精确人工批准。 |
| U6 唯一 create | NOT RUN | 尝试数 0，无回执、无 UID。 |
| U7 ImagePull 目标证据 | NOT RUN | 对象不存在。 |
| U8 Real Luna + Reader Run | NOT RUN | 新 Thread/Run 数 0。 |
| U9 真人独立评分 | NOT RUN | H/C 评分 PENDING；I 无 Run，不计准确率。 |
| U10 归档与评审 | BLOCKED | 私有证据已保存；后续 PR CI、独立 Review、真人评分及授权仍待完成。 |

最终只读资源状态：Healthy **EXISTS** 且 Ready，继续运行；CrashLoop **EXISTS** 且持续重启，继续产生 Event；ImagePull **ABSENT**。本轮未删除或清理任何资源。今后若要清理，须先按届时实际对象 UID、动作和影响另行批准，不能把创建许可当成删除许可。历史首次 M1=FAIL、B06=FAIL、PR #18 Host Review=BLOCKED 及 Phase 3A Mock 分数保持原结论，不计作本次真实诊断准确率。

原始只读快照、Node Event 和运行态摘要保存在 Git 忽略的私有受限目录；公开文档仅保留脱敏事实。下一步只有在真人明确批准一次精确 ImagePull create，并在动作前再次完成实时预检后，才可进入真实 ImagePull 诊断。当前不建议人工关闭 Issue #11。
