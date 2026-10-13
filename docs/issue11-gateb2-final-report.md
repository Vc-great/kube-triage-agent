# Issue #11 Gate B2 收口补记（2026-10-14，北京时间）

本页是新的只读评审，不更改历史报告、Scenario、Golden 或旧验收结论。基线 `origin/main=0202c4646ef0c5f4f6d7ee22bc8b26e5d50066bd`，分支 `codex/issue11-gateb2-closeout`。Issue #11 仍 open，PR #20 已合并。本轮 Kubernetes 写入 **0 次**；新模型 Thread/Run **0 次**。

## 证据边界与四层结论

1. **历史严格 Gate：FAIL。** 原评审未捕获 `Waiting.reason=CrashLoopBackOff`，因此按当时严格判据未满足并在第三例前停止。这一判定保持原样。2026-10-14 的第三次有限快照首次捕获该字符串，仅是新时点补充，不追改旧 Gate。
2. **当前故障证据：可证实持续异常退出和退避。** 同一 CrashLoop Pod UID、项目标签、无 owner；`phase=Running`，但 Ready=False，退出码 42，重启数从历史 4 增至本轮 18、19；管理员同 UID Event 有 BackOff，短日志出现 `required configuration REQUIRED_GREETING is missing`。前三次快照中前两次未见 Waiting 字段，第三次见 `CrashLoopBackOff`。Pod phase 不能代替容器健康判断。
3. **模型可见根因证据：以历史 ToolMessage 为准。** 既有 C Run 的 `pods_get`、`events_list`、`pods_log` 三组 Call/Message ID 均配对且 `ok=true`；当时的回答引用了该应用报错、退出码和 BackOff。管理员本轮同 UID Event 和日志是独立 ground truth，不能回填成旧模型的新增可见证据。Event 若缺 UID，只算弱线索；不得凭 YAML 设计或管理员回查推称模型看到了字段。正确配置来源、上游发布原因仍未证实。
4. **独立人工 Rubric：NOT RUN。** Codex 不代替真人给 `diagnosis_correct`、`grounding_score`、`false_positive`、`causal_overclaim` 打分；这些字段均为 PENDING。

H 的历史 Run 具有四个配对且 `ok=true` 的 Reader 调用（list、events、get、log），当时回答基于 Running/Ready、重启 0 和空日志判断健康。2026-10-14 同一 H UID 仍 Running/Ready，但重启数已变为 1，`lastState.reason=Unknown`，同 UID 有 `SandboxChanged` Event；不能把当前新状态归入旧 Run 的 ToolMessage，也不能擅断应用根因。

## C0–C6 本轮矩阵

| 项 | 状态 | 依据与停止点 |
| --- | --- | --- |
| C0 远端基线与隔离 | PASS | 已 fetch；新独立工作树基于最新 main，主 checkout 未改。清单及指定代码、文档、脚本均存在；本轮不改应用代码或 YAML。 |
| C0 development 运行态 | BLOCKED | development 运行态本轮未就绪；未重启，也未发起模型请求。模型 High 仍仅是请求配置，实际 effort UNKNOWN。精确运行态记录仅存私有证据。 |
| C1 H/C 只读回查 | PASS（有限范围） | 目标身份、两 Pod UID/标签/归属/镜像/命令匹配，API 就绪。H 的新重启需单独关注。C 三次快照中第三次才观察到 Waiting.reason。 |
| C2 证据口径 | PASS | 上述四层区分保留历史 FAIL；真实故障、工具可见证据与管理员回查分开。 |
| C3 ImagePull 创建前 Gate | BLOCKED | Pod 名目前不存在，Manifest SHA 与预期一致，Reader RBAC 为只读，worker 请求层有余量；但 H 状态已从历史重启 0 变化为 1，development 运行态不可用。按本轮停止条件，未申请/执行创建。 |
| C4 ImagePull 真 E2E | NOT RUN | `WRITE_ATTEMPTED=false`、`WRITE_ACK=NOT RUN`、`OBJECT_UID=NOT RUN`；无新 Thread/Run。 |
| C5 真人评分 | NOT RUN | H/C 两条真实 Run 待独立真人评分；I 未运行，不计准确率分母。旧 Mock 12/12 与 Real 分开。 |
| C6 本地文档与回归 | PASS | README 索引与本页；Ruff PASS（临时缓存）、pytest 130 passed、三份 Manifest 校验 PASS、git diff --check PASS。初次 Ruff 因工作树缓存权限失败，不计 PASS。独立 Review/新 CI 在 PR 后另查。 |

### C3 只读前提摘要

目标身份、既有对象归属和 ImagePull 名称空闲已按私有记录核对；三份清单未漂移，ImagePull SHA256 为 `77f990e474bcf0940aed43e8693f2879b3aa6db59ad24c5b5df36f3fcf593c59`。Reader 仍只允许预期的读取；两台 worker 的调度条件与请求层余量满足单个 5m/16Mi/1 Pod 的声明需求，未发现 Namespace 配额限制。Metrics API 不可用，实际资源利用率 UNKNOWN。这些只读结果不构成创建授权；H 状态变化及 development 运行态阻断后续动作。精确 Host、API、Namespace/Pod UID、资源明细和权限回执只保存在私有记录中。

## 私有证据与人工审阅表

私有审阅表已按 H/C/I 三案预填事实，四项人工分数仍 PENDING。

原始 H/C State、History、SSE 与 ToolMessage 保留在本机 Git 忽略目录 `.local/issue11-real-e2e/`；本轮只读补记的实际 UID、地址和精确 Event 归属仅在受限私有记录，不进入 PR。供真人逐案审阅时，分别填写设计诱因、管理员实际回查、模型当时 ToolMessage、Call↔Message ID、工具成功/失败、日志短摘录、诊断摘录、未知事项，并由真人记录 `human_reviewer`、`reviewed_at`、`evidence_ids`、`rationale`、`trajectory_notes` 及四项评分。H/C 评分均 PENDING；I 尚无 Run，整案 NOT RUN。

## 60–90 秒面试讲述

Graph 给模型声明四个只读 Tool Calling schema，执行时 `validate_call()` 仍按同一字段白名单和固定 Namespace 校验。旧 M1 失败是模型依原生 schema 传 selector、执行层拒绝；修复后的新 M1 以合法参数获得真实 Reader ToolMessage，旧 FAIL 不被覆盖。Healthy 的历史 ToolMessage 显示 Running、Ready 和重启 0，CrashLoop 的 ToolMessage 显示退出码 42、重启增长、BackOff 和缺少 `REQUIRED_GREETING` 的短日志。`CrashLoopBackOff` 是容器 Waiting reason，不是 Pod phase；旧快照没抓到字符串不等于没有故障，本轮晚些时候抓到也不追改旧验收。ImagePull 若以后执行，具体子原因只能按目标 Event 判断，不能从 tag 名猜测。最终质量要由真人核对 Tool Call 与 ToolMessage、Ground Truth 和因果表述，不能把 Run success 当诊断正确。

追问：① Pod phase 与容器 state 的层级和语义有何不同？② 如何隔离模型当时 ToolMessage 与事后管理员回查，避免证据偷换？③ 为什么实际创建的演示 Pod 必须按 name/UID 另行授权清理？
