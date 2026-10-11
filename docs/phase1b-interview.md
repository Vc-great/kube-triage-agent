# Phase 1B 面试问答

1. **为什么 Phase 1B 不写 KubernetesAdapter？** `graph.py:parse_demo_command()` 已直接生成四个原生工具调用；只有一个上游实现，额外业务模型会增加映射和调试成本。通用协议转换由 `mcp_client.py` 使用 `langchain-mcp-adapters` 完成。
2. **MCP Tool Schema 有什么作用？** Server 的 `tools/list` 描述工具名、参数与必填项；`mcp_client.py:_allowed_tools()` 还检查集合恰好四项。上游 `pods_log` 用 `name`、`tail`，所以 `graph.py` 必须按这个 Schema 组参。
3. **MCP Client 如何调用？** `mcp_client.py:call_tool()` 先 `validate_call()`，再通过 `MultiServerMCPClient.get_tools()` 获取 LangChain Tool 并 `ainvoke()`。URL 来自 `MCP_SERVER_URL`，Mock/Real 共用调用逻辑。
4. **为什么 read_only 还需要 RBAC？** `config.toml` 的 `read_only` 限制暴露工具，却不定义 Namespace；`reader.yaml` 的 Role/RoleBinding 在 Kubernetes API 侧把权限限于 `kube-triage-demo`。
5. **ServiceAccount 与短期 Token 如何使用？** `scripts/refresh-kubeconfig.py` 用人工 bootstrap context 申请 `kube-triage-reader` Token，写入单一 context 的 `.local/kubeconfig`；Real MCP 容器只读挂载它。Token 过期后手工轮换。
6. **Pod 日志为什么是子资源？** `pods_log` 读 `pods/log`，所以 `reader.yaml` 单独授予该资源 `get`。Graph 固定 `tail=20`，客户端上限 100，并截断返回文本。
7. **Event 如何查询？** `graph.py` 的 `events kube-triage-demo` 调 `events_list(namespace=...)`，而非传 Pod 名。Event 属于 Namespace，Role 授予 `events get,list`。
8. **工具错误和超时如何到达 UI？** `mcp_client.py:call_tool()` 用 8 秒超时并分类；Adapter `handle_tool_errors=False` 使 `isError` 抛异常。Graph 写入状态为 error 的 ToolMessage，再由 `_summarize()` 显示失败，不伪造健康结论。
9. **Checkpoint 记录了什么？** `graph.py` 的 MessagesState 中有 Human/AI/ToolMessage；Aegra 的 Postgres Checkpoint 支持 Thread 重启后的历史与 `/approve-demo` interrupt/resume。MCP 结果只保留有界文本，但历史仍可能含查询内容。
10. **为什么称为确定性 Agent Demo？** `graph.py:_route()` 和 `parse_demo_command()` 以固定规则选工具，没有 LLM 规划、推理或修复。面试时应明确说它演示协议和权限链路，不宣称自动诊断。
