# Phase 2 面试口语题

以下回答基于本仓库当前实现；离线 Fake Model 通过不代表 Real Model 验收通过。

## 1. LLM Call、Tool Calling、Agent、Workflow 有什么关系？
**口语回答：** LLM Call 是一次推理；Tool Calling 是模型输出结构化调用意图；Agent 根据结果反复决策；Workflow 由代码规定步骤。**代码位置：** `graph.py:_llm/_after_llm/_execute_tool`。**原理：** 条件边由模型是否返回 `tool_calls` 决定。**追问：** 没有调用工具的模型回复算 Agent 吗？本项目不算完成工具验收。**边界：** 默认命令路径仍是固定 Workflow。

## 2. `bind_tools` 是否执行了 MCP 工具？
**口语回答：** 没有；它只向模型声明 Schema。模型返回调用后，我们再验证并执行。**代码位置：** `graph.py:_llm`、`mcp_client.py:_allowed_tools/call_tool`。**原理：** Discovery、选择、执行是三个阶段。**追问：** 为什么不能信模型参数？模型输出不具授权含义。**边界：** 供应商必须支持标准 Tool Calling。

## 3. 为什么选 `StateGraph(MessagesState)`？
**口语回答：** 它保存 Human、AI、Tool 消息，条件边自然形成 ReAct 循环。**代码位置：** `graph.py:builder`。**原理：** `MessagesState` 合并消息，`_after_llm` 决定返回 tools 或 END。**追问：** 循环如何停止？模型最终回复或执行预算。**边界：** 仅一个 Graph，无多 Agent。

## 4. 多个 Tool Calls 如何对应结果？
**口语回答：** 遍历同一 AIMessage 的每个调用，分别返回带相同 `tool_call_id` 的 ToolMessage。**代码位置：** `graph.py:_execute_tool`。**原理：** 对话协议要求一一配对；拒绝和超预算也要配对。**追问：** 为什么不用并行？四工具、六次预算，顺序更易审计。**边界：** 没有线程池或队列。

## 5. 怎么防止无限工具循环？
**口语回答：** 最近一次 HumanMessage 后最多四次模型决策、六次工具执行，Graph 递归上限兜底。**代码位置：** `graph.py:_current_turn/_counts/_llm/_execute_tool`。**原理：** 预算在执行层，不能只写在提示词里。**追问：** 第二问会继承预算吗？不会，从最新 HumanMessage 重算。**边界：** 超额后给终止提示，不做额外总结模型调用。

## 6. Aegra、Stream、Checkpoint 分工？
**口语回答：** Graph 产生消息；Aegra 暴露 Thread/Run/SSE 并持久化；Web `useStream` 展示。**代码位置：** `server/aegra.json`、`apps/web/src/providers/Stream.tsx`。**原理：** 用户看到的是运行时 AIMessage 与 ToolMessage，非前端合成。**追问：** 重启后如何恢复？Aegra 的 Postgres Checkpoint。**边界：** Phase 2 尚无真实 LLM 浏览器验收。

## 7. 如何防 Prompt Injection？
**口语回答：** 提示词把日志视为数据；`validate_call` 限工具和参数；MCP 只读配置与 Kubernetes RBAC 继续限权。**代码位置：** `prompts.py`、`mcp_client.py`、`infra/k8s-mcp/config.toml`、`infra/k8s/reader.yaml`。**原理：** 模型被诱导时，执行层仍拒绝。**追问：** Prompt 单独可靠吗？不可靠。**边界：** 无完整内容脱敏器；展示上限为 16 Ki 字符。

## 8. Tool failure 与 LLM failure 怎么区分？
**口语回答：** MCP 返回带类型的错误 ToolMessage，模型可据此说明证据缺失；模型 429/超时由 `_llm` 直接给失败消息。**代码位置：** `mcp_client.py:_error_type/call_tool`、`graph.py:_llm`。**原理：** 失败不是诊断成功。**追问：** 403 与 404 分别意味什么？权限不足与对象不存在。**边界：** 错误展示为简化中文类别。

## 9. 根因的确定性如何表达？
**口语回答：** Pod 状态、Event 与日志互相支持才能提高判断；仅 CrashLoopBackOff 说明重启，不证明具体原因。**代码位置：** `prompts.py:SYSTEM_PROMPT`、`tests/fixtures/`。**原理：** 分开观察、证据、假设、未确认项。**追问：** Running 是否健康？不一定，容器可能 CrashLoop。**边界：** Fake fixtures 不代表真实集群故障。

## 10. 怎么评价 Agent？
**口语回答：** 记录期望与实际工具名/参数、根因证据引用质量、无依据断言、延迟、Token 与成本。**代码位置：** `tests/test_phase2.py`、`mcp_client.py` 的耗时审计。**原理：** 既测工具选择，也测结论可信度和预算。**追问：** Fake 测试能测真实模型选择准确率吗？不能，需真实模型样本集。**边界：** 当前没有自动化真实模型评测集或 Token 成本指标。

## 11. 为什么暂不加 RAG、多 Agent、HITL 修复？
**口语回答：** 本轮目标是可复现地证明一个模型能选择原生只读工具并据证据推理，额外系统会扩大风险和排障面。**代码位置：** `graph.py:builder`、`infra/k8s/reader.yaml`。**原理：** 单循环职责清楚；审批仅旧 `/approve-demo`。**追问：** 何时加知识检索？先有可靠的真实评测和明确资料需求。**边界：** 不做自动写操作。

## 12. 与行业最佳实践还有什么差距？
**口语回答：** 当前是学习 Demo：只限一个 Namespace 和四工具，没有强制结构化引用校验、敏感内容分类、生产级遥测或多模型评测。**代码位置：** `prompts.py`、`mcp_client.py`、`docs/phase2-validation.md`。**原理：** 执行安全边界已做，诊断质量仍需真实样本检验。**追问：** 下一步优先什么？真实模型 Tool Calling、浏览器 SSE 与证据评分。**边界：** 不把离线通过写成 Real PASS。
