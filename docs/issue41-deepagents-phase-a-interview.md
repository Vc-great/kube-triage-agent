# Issue #41 Phase A 面试复盘

一句话：这个 PoC 证明真实 Deep Agents Harness 可以在隔离 Aegra 中与四个原生 Reader MCP、SSE 和持久 Checkpoint 协作；它尚未证明真实模型对低信任证据的语义安全，也未实施 Planning 或 Context Offloading。

## 60–90 秒口语回答

“项目原来已经有 LangGraph StateGraph，处理只读诊断、Memory、审批修复和上下文裁剪。我没有把它迁移掉，因为这会扩大回归面；我从最新主线单独建 Worktree，加了一个默认不注册的 Deep Diagnosis Graph，用真实 `deepagents` 0.7.28 构造。Deep Agents 给了我 Harness、Middleware 和 Backend 的实践对象，但我先关闭 Subagent、摘要和虚拟文件工具，只把四个 Kubernetes Reader 通过原来的 MCP 校验层接进去。执行边界再校验工具名、每轮四次模型决策与六次 Reader 调用；并行超预算调用也有同 ID 错误回执。

验收时我用 FakeModel、合成 Mock MCP、独立 Compose 的 Postgres/Redis 和 Aegra 0.10.8，实际跑通两轮 Thread/Run/SSE，检查 State、History 和 Tool Call ID，重启 Aegra 后同一 Thread 还能继续。第一版 FakeModel 漏了流式方法，SSE 曾尝试走无效 Key 的 Provider 路径，我停下并改成没有 Provider 客户端的 BaseChatModel，再重跑通过。这说明仅有 graph.invoke 单测并不足以证明协议和成本边界。

目前仍是 NO-GO：真实模型的工具披露、日志注入与 UID 冲突的语义行为、取消和重连还没有完整证据。Planning 是否值得增加 Token 成本要等下一阶段在相同冻结案例下比较；StateBackend 中的虚拟材料也不能替代原始 Reader ToolMessage 和当前 UID 证据。原 Agent 保留为可用基线，下一阶段须单独决定与授权。”

## 递进追问

1. **为何选 Deep Agents 而不是只扩展 LangGraph？** 本阶段目标是检验 Harness 的真实 Middleware、Profile、Backend 组合及 Aegra 兼容性。原 LangGraph 路径已承担正式诊断与审批，保留它才能做可撤销、可对照的研究；PoC 尚未证明 Harness 更好。
2. **`tools=[四个工具]` 为什么不足以保证安全？** Harness 会额外注入文件、Subagent 等工具。要检查模型最后收到的名称集合，还要在执行前拒绝未授权名称。SDK 的工具排除代码自身也说明排除机制不应单独视为安全边界。
3. **并行 Tool Call 如何守住预算和 ID？** 以本轮 HumanMessage 为界，计数已完成 ToolMessage，再按当前 AIMessage 中 Tool Call 的稳定位置决定是否执行。每个调用无论成功、失败或超预算，返回对应 `tool_call_id`；错 ID 回执被替换成安全错误。
4. **StateBackend 和 Context Offloading 能证明什么？** 本阶段只证明使用 StateBackend 时不暴露文件工具，没有做 Offloading。未来即使保存虚拟调查笔记，笔记也不能代替原始 Reader 回执；被 16 KiB 入口截断的数据无法通过后续 Offloading 恢复。
5. **Planning 的额外成本值得吗？** 现在没有真实模型 Usage 或 A/B 数据，不能估算真实 Token 或宣称收益。后续需按简单/复杂冻结样例比较准确率、错误结论、模型调用、Reader 调用与延迟，并经用户单独授权模型成本和合成数据云端发送。
