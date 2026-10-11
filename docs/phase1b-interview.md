# Phase 1B 面试问答

> 以下原有问答描述代码设计与 PR #3 Mock 证据。本轮另外验证了受限 kubectl、RBAC、TLS、Real MCP 四工具及 Aegra ToolMessage/SSE；浏览器展示仍未运行，详见 [执行记录](phase1b-real-e2e.md)。面试时必须区分这几层证据。

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

## 对照实际代码与本轮数据流

| 主题 | 当前代码位置 | 本轮实际过程 | 设计原因 | 面试官追问 |
| --- | --- | --- | --- | --- |
| MCP Tool 与 kubectl/API | `graph.py:parse_demo_command()`、`mcp_client.py:call_tool()`、`config.toml` | 受限 `kubectl` 与 Real MCP 分别读取真实 Pod/Event/Log；它们是两条独立的 Kubernetes API 客户端路线 | 直接用上游四个原生工具名与 Schema，省去业务 Adapter/DTO | `tools/list` 成功能证明 Pod 可读吗？不能，必须实际 `tools/call` 并核对对象来源 |
| SSH、Docker 与 TLS | `infra/compose.yaml:k8s-mcp`、`refresh-kubeconfig.py` | `ssh k8s-m` 远端 kubectl 成功；Mac/项目 API 容器连 `192.168.31.136:6443`；容器以 CA 验证 `/livez` 为 200，Real MCP 带 CA 的受限身份完成四次 API 读取 | SSH 是管理通道，容器访问 API 是另一条网络路线；CA 和证书 SAN 防止错误端点 | SSH 通而容器不通怎么办？分层查路由、地址与证书，不关闭 TLS 校验 |
| ServiceAccount、Role、RoleBinding、日志子资源 | `infra/k8s/reader.yaml` | 项目 SA 的受限 kubeconfig 对目标 `pods/events` 的 get/list 与 `pods/log` 的 get 为 yes；跨 Namespace、Secret 和写为 no，真实越权请求为 403 | SA 定义身份，Role 定义命名空间内权限，RoleBinding 绑定二者；`pods/log` 是独立资源 | `pods get` 能自动读日志吗？不能，需单独授予 `pods/log get` |
| Client/MCP/RBAC 三层限制 | `mcp_client.py:validate_call()`、`config.toml`、`reader.yaml` | Real Aegra 对跨 Namespace 命令返回 `Namespace denied`；MCP `tools/list` 恰好四读工具；真实 API 越权请求返回 Forbidden | Client 约束应用调用，MCP 配置控制可见工具，RBAC 是 API 最终授权；前两层不能代替 RBAC | `read_only=true` 为何不够？它不限制 Namespace，也不能约束绕过 MCP 使用 Token |
| 短期 Token、401/403 | `refresh-kubeconfig.py`、`mcp_client.py:_error_type()` | SSH 来源生成 24h 受限 Token，`.local` 为 0700、kubeconfig 为 0600；独立无效 Token 经验证 TLS 后返回 401，真实越权为 403；未等待 Token 过期 | 不把管理员身份给容器；手工刷新即可，无需轮换平台 | 401 看凭据有效期/身份，403 看 Role、RoleBinding 和 Namespace；不能混为一谈 |
| 原生 Schema、ToolMessage、Checkpoint、SSE | `graph.py:parse_demo_command()`、`_execute_tool()`、`_summarize()`；`mcp_client.py:_allowed_tools()`；`infra/compose.yaml` | 四条 Real Aegra 命令分别有正确 tool_calls、ToolMessage、SSE 和真实对象；Mock 回归证明 Postgres Checkpoint 与模拟审批重启持久。浏览器展示仍 NOT RUN | 原生参数便于追踪；结果限制 16Ki，8 秒超时，避免无限内容进入 UI/Checkpoint | 浏览器显示文字能证明真实 MCP 吗？还需核对工具名、参数、ToolMessage、SSE 与非 `mock=true` 的集群对象 |
| 固定规则与未来阶段 | `graph.py:_route()`、`parse_demo_command()`、`_approval()` | 四类命令由字符串规则选择工具，`/approve-demo` 仅模拟 interrupt/resume；没有模型规划、真实修复 | Phase 1B 先缩小权限与协议故障面，便于复现和解释 | 这是自主 Tool Calling 吗？不是；LLM 选工具与故障诊断属于后续 Phase 2，尚未实现 |

本轮两个可讲的真实故障及修复：`triage-sample` 因节点无法直连 Docker Hub 进入 `ImagePullBackOff`，从 Mac 经代理拉取精确 amd64 镜像并流式导入该节点缓存后成功；运行中 Compose 五容器来自两个旧 worktree，先核对项目标签与卷，再把主工作树快进至 `origin/main` 并选为唯一后续操作目录。浏览器结果仍需用户手动输入本地 API Key 后复核，不能把 HTTP/SSE PASS 说成 UI PASS。
