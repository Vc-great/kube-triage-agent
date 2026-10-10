# Phase 1A 面试讲解

以下回答只描述当前仓库的真实实现；“Kubernetes 数据”全是静态 Mock。

## 1. MCP 与 Function Calling 有什么区别？

**口语回答：** Function Calling 通常指模型给出“调用哪个函数、用什么参数”的决定；MCP 定义客户端怎样发现并通过协议调用外部服务的工具。二者可以结合：模型生成 Tool Call，MCP 执行它。本项目没有模型，`parse_demo_command()` 用规则生成 Tool Call，但后半段确实跨容器走 MCP。

**代码：** `graph.py:parse_demo_command`、`mcp_client.py:call_tool`、`mock_mcp.py`。**追问：** “把 Python 函数命名为 MCP 工具算吗？”不算，必须发生 MCP 握手和 transport 请求；可看 `mock-mcp` 的 `POST /mcp` 日志。

## 2. MCP Client、Server、LangGraph ToolNode 各做什么？

**口语回答：** Client 连接外部 MCP Server，发现工具并调用；Server 暴露固定数据工具并再次校验参数；LangGraph 的工具执行节点把 Tool Call 变成调用结果，写回 Agent State。本轮节点名叫 `tools`，直接调用 adapter Tool；没有用预制 `ToolNode`，因此更容易展示错误与审计边界。

**代码：** `mcp_client.py:_allowed_tools/call_tool`、`mock_mcp.py`、`graph.py:_execute_tool`。**追问：** “为什么校验两次？”客户端白名单限制 Graph 能调用什么，Server 校验保护服务本身，防止其它容器直接绕过 Graph。

## 3. 一条消息怎样往返？

**口语回答：** 浏览器带 Key 向 Aegra 发 Run 的 SSE 请求；Aegra 先认证，再恢复 Thread 的状态并执行 `agent` Graph。`pods demo` 被固定规则变为 `list_pods`；adapter 发 `POST /mcp` 到独立容器；静态结果写入 ToolMessage，Graph 给出摘要；Aegra 把状态更新通过 SSE 送回 UI。

**代码：** `Stream.tsx`、`auth.py:authenticate`、`graph.py:_route/_request_tool/_execute_tool/_summarize`。**追问：** “谁提供 SSE？”Aegra Agent Protocol；Graph 只产生状态更新。

## 4. 为什么不能暴露全部 MCP 工具？

**口语回答：** 工具可能包含写操作或越权查询，Prompt 和前端隐藏按钮都不是强制边界。真正执行前，服务端 `call_tool()` 只接受三个只读工具，Mock Server 又只允许 `demo` Namespace。

**代码：** `mcp_client.py:ALLOWED_TOOLS/validate_call`、`mock_mcp.py:check_namespace`。**追问：** “LLM 忽略 Prompt 怎么办？”它仍过不了执行层校验；当前根本没有 LLM。

## 5. Aegra 认证解决什么？

**口语回答：** 它在后端校验每个业务 API 请求，包括直接读 Thread/History、发 Run、SSE 和 Resume。前端登录按钮只改变页面，别人仍能直接发 HTTP 请求。我们使用单个随机 Token 与固定身份，仅适合本机 Demo。

**代码：** `aegra.json:auth.path`、`auth.py:authenticate`、`scripts/acceptance.py:denied`。**追问：** “能做多用户隔离吗？”当前不能；固定身份没有细粒度所有权规则。

## 6. MCP 超时或断连怎么办？

**口语回答：** 每次发现或调用都最多等 8 秒；连接失败、超时、工具拒绝会映射成不同的简短信息并写审计。不能无限重试，因为会耗住 Run、制造重复请求，并掩盖故障。

**代码：** `mcp_client.py:call_tool/_error_type`。**追问：** “断连实测了吗？”停止本项目 `mock-mcp` 后，Run 约 0.43 秒返回“服务暂时不可用”；测试后已恢复服务。

## 7. State、Thread、Run、Checkpoint 的关系？

**口语回答：** Thread 是一条对话；每次执行是 Run；Graph 的 State 是消息等数据；Checkpoint 是每一步保存的状态快照，让审批中断后能用 `Command(resume=...)` 续跑。Aegra 提供 API、线程/运行管理与持久化集成，LangGraph 定义状态流转和中断。

**代码：** `graph.py:builder/_approval`、`scripts/acceptance.py:state/stream`。**追问：** “API 重启后还在吗？”同一个 Thread 的 State/History 实测仍在；Worker 崩溃恢复本轮未测。

## 8. 哪些是真的、哪些是 Mock、Phase 1B 才做？

**口语回答：** 真的有 Aegra 认证、Thread/Run/SSE/Checkpoint、跨容器 MCP 协议、规则路由与审计；Pod、Event、Log 都是固定 fixture，审批也不触发集群操作。真实只读 Kubernetes MCP 与 LLM 自主选择工具还没做。

**代码：** `auth.py`、`mcp_client.py`、`mock_mcp.py`、`graph.py`。**追问：** “能直接接生产集群吗？”不能；需要独立实验 Namespace、最小权限凭据、只读验证与更完整安全评审。
