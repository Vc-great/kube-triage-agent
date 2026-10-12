# Phase 2B 面试问答：结合代码与本轮证据

本轮在用户明确批准外部模型载荷后，`deepseek-flash` 于独立栈真实发出 Tool Calls，经 Mock 和项目专属 Real MCP 读取。Real 浏览器 Thread `141cfc77-1a70-41c6-a8e1-ed50741e57d6` 的最终结论是 `triage-sample` 正常完成、未发现故障。下列回答区分本轮真实轨迹、Fake 测试与固定命令回归；详情见 [Phase 2B 验收记录](phase2b-real-llm-validation.md)。

## 1. 为什么 `bind_tools` 不等于执行工具？

**能说出口：** “`bind_tools` 只是把 `_allowed_tools()` 发现的四个 MCP 工具 Schema 提供给模型。模型返回 `AIMessage.tool_calls` 后，LangGraph 才走 `_after_llm` 到 `_execute_tool`，在那里调用 `call_tool`，所以选择和执行是两步。”

**代码：** `server/src/kube_triage/graph.py:_llm,_after_llm,_execute_tool`；`server/src/kube_triage/mcp_client.py:_allowed_tools,call_tool`。**典型追问：** 模型只回答文字时？`_after_llm` 直接结束，不调用 MCP。

## 2. Tool Call ID 如何关联 ToolMessage？多个调用怎么办？

**能说出口：** “`_execute_tool` 遍历同一条 `AIMessage.tool_calls`，每个调用都生成 `ToolMessage(tool_call_id=call['id'])`，所以结果靠 ID 与对应调用关联；即使预算已满，也给那个 ID 一个错误结果，避免悬空调用。”

**代码与实测：** `graph.py:_execute_tool,_counts`；`server/tests/test_phase2.py:test_multi_round_and_multiple_tool_calls_pair_exactly,test_tool_budget_pairs_rejected_calls_and_resets_next_question`。Real Thread 首轮并行调用 Pod 列表和 Event，两个 ID 均与 ToolMessage 配对。**典型追问：** 模型一轮发 8 个调用？前 6 个执行，后 2 个得到预算错误 ToolMessage；这是 Fake 测试验证的边界。

## 3. 为什么 Fake Model 通过不等于真实 Tool Calling 通过？

**能说出口：** “FakeModel 在测试中直接返回预造的 `AIMessage.tool_calls`，它验证 Graph 的分支、配对和拒绝规则，完全没有请求供应商。只有真实响应里出现可解析的结构化 `tool_calls`，才能证明该模型端点兼容。”

**代码与实测：** `server/tests/test_phase2.py:FakeModel`；`graph.py:_llm` 检查 `invalid_tool_calls`。本轮最终 38 项测试通过；另从隔离 API 容器真实请求模型，得到 `pods_list_in_namespace` 标准 Tool Call 且 `invalid_tool_calls=0`，这是独立于测试的证据。**典型追问：** 普通文字“我会调用工具”算吗？不算；`reply.tool_calls` 必须非空且可解析。

## 4. 模型收到 MCP 结果后怎样继续？循环在哪里？

**能说出口：** “工具结果作为 ToolMessage 追加到 `MessagesState`；`_after_tools` 在 LLM 模式把图送回 `_llm`，新模型决策会看到前面的用户消息、工具调用和结果，再决定继续查或给结论。”

**代码与实测：** `graph.py:_execute_tool,_after_tools,_llm` 及图边。Real Thread 首轮并行读 Pod/Event，第二轮模型根据 Pod 为 `Succeeded` 再读日志，第三轮给出“未发现故障证据”。**典型追问：** 为什么不是 MCP 直接写结论？MCP 只返回观察结果；中文诊断由下一次模型决策生成。旧固定命令路径则进 `_summarize`。

## 5. Aegra 的 Thread、Run、Checkpoint、SSE 各做什么？

**能说出口：** “Thread 是会话身份；Run 是在这个 Thread 上执行注册为 `agent` 的图；Checkpoint 保存每步状态，供 State/History 和重启后恢复；SSE 将 Run 更新作为 `data:` 事件送到前端。”

**代码与实测：** `server/aegra.json` 的 `graphs.agent`；`apps/web/src/providers/Stream.tsx` 的 `useTypedStream`；`scripts/acceptance.py` 的 `/threads/.../runs/stream`、State/History。本轮真实模型 Mock Run 的 SSE 有 `data:`，Real Thread 的 Run 为 `success`、History 有 7 项；旧回归验证 API 重启后状态仍在。**典型追问：** 页面刷新后消息从哪里来？同一 Thread 的持久化状态/历史，而非浏览器内临时数组。

## 6. 模型选错工具或参数时，为什么执行层仍要拒绝？

**能说出口：** “System Prompt 只能影响模型倾向，不能作为权限边界；`validate_call` 在执行前检查工具名、固定 Namespace、Pod 名、`tail` 范围和额外参数。模型若越权，`call_tool` 返回 policy 错误，不让请求到 MCP。”

**代码与实测：** `mcp_client.py:validate_call,call_tool`；`server/tests/test_phase2.py:test_execution_rejects_unsafe_model_calls,test_prompt_injection_cannot_expand_execution_scope`。Real API 中跨 Namespace、写工具和未知字段都得到 `policy` 拒绝；但原生合法的 `pods_log(container=sample)` 与缺省 `tail` 起初也被误拒绝，随后在校验函数内修复。**典型追问：** 工具结果里写“忽略规则”怎么办？结果是不可信数据，执行层仍按白名单检查。

## 7. MCP 白名单、`read_only`、RBAC 分别保证什么？

**能说出口：** “`_allowed_tools` 要求工具发现恰好是四个原生读工具，`validate_call` 限制每次调用；Real MCP 的 `read_only=true` 再限制服务能力；Kubernetes 的 `kube-triage-reader` Role 只允许该 Namespace 的 Pod、Event 和 Pod Log 读取。三层分别在 Agent、MCP 和 API 授权处生效。”

**代码与实测：** `mcp_client.py:ALLOWED_TOOLS,_allowed_tools,validate_call`；`infra/k8s-mcp/config.toml`；`infra/k8s/reader.yaml`。本轮 Real MCP 发现恰好四工具并实际读取；受限身份对本 Namespace 的 Pod/Event/Log 为 `yes`，对 `kube-system`、Secret、Pod 写入为 `no`。**典型追问：** 若模型调用 `pods_delete`？Agent 白名单先拒绝，本轮 Real API 实测为 `policy` 错误。

## 8. 怎样判断报告有依据？正常 Pod 为什么不能编故障？

**能说出口：** “把报告中的现象和原因逐条回指 Pod 状态、Event、Log 的实际 ToolMessage；工具失败或证据不足就写不确定。`phase=Running` 也要看容器状态，但 `Succeeded` 且日志正常的 Pod 不能凭 Demo 需要说成 CrashLoop。”

**代码与实测：** `prompts.py:SYSTEM_PROMPT`；`graph.py:_llm` 消费 ToolMessage；`server/tests/fixtures` 是静态样本。Real Thread 的 Pod `Succeeded`、退出码 0、重启 0、日志正常，模型据此回答“未发现故障”，并说明当前 Event 为空可能有保留时间因素。**典型追问：** Mock 的 `database unavailable` 能证明真实数据库故障吗？不能，它只在 fixture 里，必须标 `mock=true`。

## 9. 4 次模型决策 / 6 次工具预算解决什么？与 Token/花费有何区别？

**能说出口：** “`MAX_MODEL_DECISIONS=4` 防止模型无限来回；`MAX_TOOL_CALLS=6` 限制一次用户问题里真正执行的工具数。它们是控制流上限，不是 Token 或费用上限；一次决策仍可能有很多输入 Token，成本要看供应商实际 usage 和价格。”

**代码与实测：** `graph.py:MAX_MODEL_DECISIONS,MAX_TOOL_CALLS,_counts,_llm,_execute_tool`。首次 Real Run 因两次合法参数被误拒绝，4 次决策后只给预算提示；修复后 3 次决策、3 次工具就完成报告，用量为 7442 输入/1177 输出 Token。**典型追问：** 下一问预算如何重置？`_current_turn` 从最后一条 HumanMessage 开始计数。费用仍需供应商账单/价格，不能由预算推算。

## 10. 供应商不支持 Tool Calling，如何定位？

**能说出口：** “先确认隔离 API 里 LLM 开启且模型、Key、URL 生效，再确认 `_allowed_tools` 的四工具发现成功；用一条无敏感问题检查供应商原始 `AIMessage.tool_calls` 与 `invalid_tool_calls`，按实际 HTTP 状态、TLS、超时或 429 分类。只有普通文字或解析失败都不能算 Tool Calling PASS。”

**代码与实测：** `llm.py:enabled,chat_model`；`graph.py:_llm`；`mcp_client.py:_allowed_tools`。本轮最初被自动审批阻断，用户明确授权后从隔离 API 容器获得真实标准 Tool Call、`invalid_tool_calls=0`，因此当前端点在该模型下支持本轮所需的 Tool Calling。**典型追问：** 如果只得到文字或 `invalid_tool_calls`，怎么办？先记录原始响应和状态码，再定位模型端点兼容性，不能换 Fake Model 冒充通过。
