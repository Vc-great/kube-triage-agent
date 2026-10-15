# Issue #28 Gate A：面试讲述稿

## 60–90 秒回答

“我给一个基于 LangGraph 的 Kubernetes 诊断助手加了默认关闭的上下文预算。原来 `_llm()` 每次把整个 Checkpoint 历史送给模型，长 Thread 会逼近上下文上限。Gate A 先做确定性估算：把固定系统提示、四个只读工具 Schema、消息和结构化 Tool Call 序列化成 UTF-8，按字节数折算并加 20% 边际、2048 输出预留。这个值不是 Provider Token。超限时，我只从最旧的完整用户轮次开始删，要求 Tool Call 与 ToolMessage ID 一一配对，当前轮全部保留；遇到残缺历史或只留当前轮仍超限，就停止模型调用并明确诊断未完成。裁剪只作用于 `ainvoke` 的临时输入，State 和 MemorySaver 的完整历史不变，`/repair-demo` 审批路径也不进入这个组件。离线用 10/20/30 轮、并发工具、恶意日志、预算拒绝和 Checkpoint 回归验证，最终 240 个 pytest 通过。没有做真实模型、集群写入或摘要压缩，所以实际 Token 和费用效果仍待授权验证。”

## 递进追问

1. 为什么以完整轮次为裁剪单位？如果历史中出现孤儿 ToolMessage 或重复 Tool Call ID，如何处理？
2. 为什么把工具 Schema 和输出预留计入同一预算？估算值与 Provider 实际 Context Limit 不一致时怎样失败关闭？
3. 如何证明临时送模视图不会改写 Checkpoint 或绕过人工审批？离线测试仍不能证明哪些真实模型行为？
