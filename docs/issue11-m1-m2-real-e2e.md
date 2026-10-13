# Issue #11 · Luna High 的 M1 实测与 M2 停止记录

日期：2026-10-13（北京时间）。本轮基于 `origin/main=25e0010c4c882a3ce7c0842a38c1f582b41cf3b6` 的独立工作树。Issue #11 仍 open；PR #17/#18/#19 已合并。历史 Phase 3A 12/12、Grounding 1.50/2、Phase 3B B06=FAIL、PR #18 独立 Review=BLOCKED 均保留原样。

## 实际运行边界

- 主 checkout 的私有 `.env` 已更新为 `gpt-6-luna`，但运行中的 Mac development 服务原先仍读取旧 `.local/dev.env`。本轮只把模型 ID、Provider URL、模型 Key 同步到私有 development 配置，保留 `kube_triage_agent_dev` 数据库/用户、独立 Redis、回环 Reader URL 和两个 `REPAIR_* = false`。未更改正式 `.env` 或 dev01 Compose。
- 通过项目官方 `make dev-stop` 停止原生旧服务，再从本独立工作树以 `make dev` 启动。API/Web/SSH 隧道的进程工作目录与工作树匹配，development API 健康且拒绝无认证请求。当前分支的 Graph、LLM、Prompts、Reader 文件 SHA256 分别为 `f3ba127062d7a1b93b1e566bde942eac68f5391c75b0d24e77a6805d932c4fb3`、`ade2f2e343d7c1d97e040022622bdfb562b783bdfe097b20e97aec3edb172571`、`0c9b3765a6d939259755fd6af8cbac7b8020ff43fe65d5856a14b940065980c9`、`87e64f58a6b962a49aec1d6941af605c1e476d8e3b117b90dfe49a62c62e4958`。
- 锁定的 `langchain-openai==1.7.0` 支持 `use_responses_api` 与 `reasoning`。本轮代码只在 `TRIAGE_ENV=development` 且模型名为 `gpt-6-luna` 时请求 Responses API 与 `reasoning.effort=high`；30 秒超时、`max_retries=1`、Graph 的 4 次模型决策和 6 次工具调用上限未变。其他模型路径未更改。
- Provider 的模型目录列出 Luna，Responses 路由可达。M1 返回 `model_name=gpt-6-luna`、Responses `response` 对象和可配对的标准 Tool Call/ToolMessage；服务端没有回显实际 reasoning effort，因此只能证明请求配置为 High，不能证明模型内部实际 effort。仅发现四个原生 Reader 工具；未暴露 Repair 工具。

## M1：一次 Thread / 一次 Run

先通过真实 Reader 的 `pods_get` 独立只读确认既有演示 Pod 为 Running、容器 Ready；此预检未调用模型。随后仅建立一个新的 development Thread，提交一次中性问题，要求模型只读判断该 Deployment 的 Pod 是否 Running/Ready。SSE 有 `end`、无 `error`，Run status=`success`，State/History 完整；这只表示协议运行结束。

模型进行了 4 次决策并生成 4 个标准 Tool Call，均调用 `pods_list_in_namespace`，Call ID 与 4 条 ToolMessage ID 一一对应。每次请求都附带 `fieldSelector` 或 `labelSelector`，而执行层对该工具只允许 `namespace`；因此 4 条 ToolMessage 全为 `ok=false`、`error_type=policy`，没有成功获取 Pod 结果。模型最后返回“达到本轮模型决策上限，请人工核查”。**M1=FAIL**：没有可支撑 Running/Ready 诊断的真实 Reader 结果，也没有完成证据型回答。协议成功和模型名称正确不能代替诊断通过。

此次唯一 Run 的 usage 合计输入 5,513、输出 334、总计 5,847 tokens（包括服务端报告的 reasoning tokens）；没有额外付费 Probe 或重试新 Run。原始 SSE、State、History、Call 参数、工具回执与标识仅保存于 Git 忽略的 `.local/issue11-real-e2e/`，目录权限 0700、文件权限 0600；本页不发布内部地址、资源 UID 或原始日志。

直接故障点是 **模型可见的 MCP 工具参数与 `validate_call` 实际白名单不一致**：只读查询确认列表工具的 schema 暴露 `namespace`、`fieldSelector`、`labelSelector`，执行层仅接受 `namespace`。后续最小修复应让模型绑定的工具 schema 只暴露执行层允许的参数，并以新的、单独获准的真实 Run 验证；本轮的 M1 不因代码修复而改判，也不补发第二次 Run。

## Kubernetes 只读快照与停止

M1 前只读复核了指定 SSH Host/context/API readyz、Namespace 身份与项目标签、既有 Deployment 1/1、其 Pod Running/Ready、既有对照 Pod Succeeded、三目标名称空闲。Reader SA/Role/Binding 归属正确，只允许 pods/events get/list 与 pods/log get；get secrets、create pods、update deployments/scale 均被拒。两个 worker Ready、未 cordon、无 taint/Pressure，请求层分别至少可容纳三份清单合计的 20m CPU、64Mi、3 Pod；Quota/LimitRange 为空。Metrics API 不可用，真实 CPU/内存利用率为 **UNKNOWN**。三份 YAML 的 SHA256 与本轮授权文本逐字节一致，离线 Manifest 校验通过。

由于 M1=FAIL，本轮未进入任何 create 前的再次预检，没有发出 Kubernetes 写请求，也没有 M2 Thread/Run。最终只读回查三个目标 Pod 均不存在：`triage-case-healthy`、`triage-case-crashloop`、`triage-case-imagepull` 全为 **NOT RUN / 无 UID**。创建授权未被本轮消耗；未来是否继续，应先修复工具 schema 契约并另行制定 M1 验证。若未来确实创建 Pod，删除仍需按实际 name/UID/影响取得新授权，本轮没有清理动作。

## Gate 矩阵

| Gate | 状态 | 本轮证据或停止原因 |
| --- | --- | --- |
| G00 最新 main、独立工作树、运行版本 | PASS | fetch 后 main 与工作树基线一致；运行进程来自本工作树。 |
| G01 Luna、Responses、High 请求兼容 | PASS | 模型标识与 Responses 对象可核对；High 为请求配置，服务端实际 effort UNKNOWN。 |
| M1 真实模型 + 真实 Reader 证据型回答 | FAIL | 四次 Tool Call/ToolMessage 配对，但全部被参数策略拒绝；无成功 Reader 结果。 |
| K1 身份、RBAC、Node requests、Hash、空名称 | PASS | 只读时点快照通过；实际利用率 UNKNOWN，未执行 create 前复检。 |
| K2-H / M2-H | NOT RUN | M1 失败后停止，Healthy 未创建、未诊断。 |
| K2-C / M2-C | NOT RUN | CrashLoop 未创建、未诊断。 |
| K2-I / M2-I | NOT RUN | ImagePull 未创建、未诊断。 |
| R01 最终目标状态与清理边界 | PASS | 三目标均不存在；无删除/回滚授权或动作。 |
| R02 中文报告、私有证据、Draft PR | PASS | 私有证据及本报告已形成；CI/Review 以本 PR 实时结果为准。 |

Human Review = **NOT RUN**；真实三案诊断通过率不可计算，不能报为 0/3 的模型准确率。程序性检查为 M1 **FAIL**，Grounding 人工评分 **UNKNOWN**。本轮没有覆盖历史 Golden 或改写 Phase 3A/B 验收。

## 面试讲述与追问

**60–90 秒讲述：**“我先核对最新 main、独立工作树和正在运行的开发进程，发现用户更新的是主目录 `.env`，开发进程仍使用旧模型配置。我只同步模型相关字段到私有开发配置，保留独立数据库、Redis 和只读 Reader，然后从验证过的工作树启动。Luna 通过 Responses API 返回了标准 Tool Call，四次调用和 ToolMessage ID 都能配对，说明模型与协议确实连通。但模型给列表工具加了执行层不接受的 selector 参数，四次都被策略拒绝，最终达到决策上限。Run status 虽是 success，却没有一条成功的 Kubernetes 证据，所以 M1 判 FAIL，立即停止三个故障 Pod 的创建。只读预检与真实诊断分开记录，历史 Mock 分数也没有充当真实准确率。”

追问：

1. 为什么 `Run success` 不等于诊断成功？因为 Graph 正常结束仍可能只有工具拒绝和预算提示，需要核对 `ok`、目标身份和最终结论证据。
2. 如何修复本次参数冲突？让模型可见工具 schema 与执行层白名单一致，并用新 Run 验证标准 Tool Call、工具结果和二次模型回答。
3. 为什么没有继续创建故障 Pod？M2 的明确前置条件是 M1 真实工具链通过；本轮四次调用全失败，继续写入无法得到可信评测。
