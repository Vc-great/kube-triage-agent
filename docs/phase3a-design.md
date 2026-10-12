# Phase 3A：诊断质量评测设计

这是单用户学习 Demo 的小样本效果评测。真实模型只接收中性合成问题、现有 System Prompt、四个原生工具 Schema 和 Mock MCP 生成的数据。评测不访问真实 Kubernetes。

## 真实数据流

`server/aegra.json` 将 `agent` 指向 `graph.py:graph`。每次运行建立新 Aegra Thread，`LLM_ENABLED=true` 时 `_route` 进入 `_llm`。`_llm` 从 `mcp_client._allowed_tools` 发现恰好四个原生只读工具，向模型发送 `prompts.SYSTEM_PROMPT` 与本 Thread 消息。模型的 `AIMessage.tool_calls` 经 `_after_llm` 进入 `_execute_tool`；`call_tool` 先执行白名单、固定 Namespace、参数校验，再读 Mock MCP；每个调用都产生同 ID 的 `ToolMessage`。`_counts` 只统计当前用户轮的模型决策和工具消息，限制为 4/6。工具结果进入下一次模型决策，最终中文回答写入 Checkpoint。

`scripts/eval_phase3a.py` 经 Agent Protocol 创建 Thread、消费 Run SSE、读取 State/History 和 Run 状态。它只从**本次新 Thread 的 State**提取调用、结果和终答，防止用 Golden 或旧 Thread 补证据。SSE 完成且 State 无待续节点，并且终答不是预算/错误提示，才计作正常完成。ToolMessage ID 一一配对、工具参数合规、Mock 响应成功、目标证据充足分别记录，互不代替。

## Golden 与 Mock

`eval/cases.json` 仅有 CrashLoopBackOff、ImagePullBackOff、OOMKilled、健康四项。问题只说调查 Pod，不透露预期分类；Golden 的标签、必要证据枚举、禁止断言只用于评测，不进入模型提示或 MCP 响应。`server/src/kube_triage/fixtures/*.json` 是唯一的合成事实源，`mock_mcp.py` 与离线测试共用。Pod phase 与容器状态分开：CrashLoop Pod phase 为 Running、容器 Waiting；OOM Pod 当前 Running，但 `lastState.terminated.reason=OOMKilled`；ImagePull Pod Pending，尚无容器日志。`events_list(namespace)` 返回四个 Pod 的全 Namespace 事件，每条带 `involvedObject.name`。健康 Pod 的正常 Event 与其它 Pod 的 Warning Event 同时出现，强制检查事件归属。

## 指标与分母

- 计划数固定为 4×3=12；Run 失败与 BLOCKED 均保留在行记录和分母。完成率＝正常结束 Run/12。
- 工具协议通过率＝Tool Call ID 与 ToolMessage ID 完整一一配对的 Run/12。工具选择合规率另计；安全拒绝不会变成成功检索。
- 关键证据取得率＝本次 Run 取得 Golden 所需、属于目标 Pod 的成功 Mock ToolMessage 的 Run/12。它不评价最终措辞。
- 诊断正确率＝人工判为正确的 Run/12；平均 grounding＝人工 0–2 分总和/12。健康误报率＝健康 Run 中明确误报故障的次数/3。失败 Run 也需人工登记 0 或注明待评；未审完时报告为 PENDING，不推测。
- 延迟取每次 Run 实测墙钟耗时的中位数和最大值；Token 只累加 AIMessage 的实际 `usage_metadata` 或供应商 `token_usage`，缺失为 `null`。无可靠价格时不算费用。

人工 rubric：`diagnosis_correct` 是分类和不确定性是否合理；`grounding_score=0/1/2` 分别表示严重编造、部分证据但越界、主要陈述有对应 ToolMessage 支持；`false_positive` 只用于健康样本；`review_notes` 引用具体回答句与工具 ID。严禁通过中文关键词自动给正确率。原始合成证据仅在 Git 忽略的 `.local/eval-runs` 私有文件中供人工复核；PR 中只放脱敏摘要。

## 边界

Prompt 与 MCP 数据信任级别不同。即使外部文本误导模型，执行层仍只准四个只读工具和 `kube-triage-demo`。这些 Mock 样本验证证据链与典型诊断，不代表真实集群的覆盖度或生产准确率。Phase 2B 已有正常 Pod 的历史 Real MCP 证据，本轮不重复访问集群。
