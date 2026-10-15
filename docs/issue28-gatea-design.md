# Issue #28 Gate A：确定性上下文预算

基线：2026-10-15 `origin/main=45d9f7896f900d3c9fe8266aa29c81923b0dbd9f`。只作用于普通诊断 `_llm()` 的临时送模视图；State、Checkpoint、History、审批和工具执行边界不变。Gate B 摘要不在此范围。

## 配置与估算

- `CONTEXT_WINDOW_ENABLED=false`，只接受大小写不敏感的 `true` / `false`；`CONTEXT_ESTIMATED_TOTAL_BUDGET=16384`，只接受十进制整数且必须大于 2048。非法值抛 `ConfigurationError`，不回退。
- 关闭时送模列表严格为 `[SystemMessage(content=system_prompt()), *state["messages"]]`，不添加警告、不重排。开启时估算完整 SystemMessage、`build_model_tool_schemas()` 返回的四个 Reader Schema，以及每条消息的类型、正文、ID、结构化 Tool Call 参数、ToolMessage 状态等 JSON 字段。
- 估算公式为 `ceil((UTF-8 JSON 字节数 / 2 + 8 × 消息数) × 1.2) + 2048`。2048 是输出预留，20% 是安全边际。此数仅是稳定的离线**估算单位**，不代表 Provider Token、实际输入上限、费用或延迟。不能 JSON 序列化的字段拒绝送模；不会按零计算。工具 Schema 每次都计入估算。

## 轮次与失败边界

最后一条 `HumanMessage` 到末尾为当前轮，全部保留。此前历史按 `HumanMessage` 切成连续整轮。可省略轮必须从 Human 开始、以没有待处理 Tool Call 的 AI 结束；轮内每个 Tool Call ID 非空且唯一，恰有一个同 ID ToolMessage，并按调用后响应的顺序出现。任何未知消息类型、无 Human、首部残片、缺最终 AI、悬挂/孤儿/重复 ID、跨轮复用 ID 都禁止裁剪。超预算时仅从最旧整轮开始逐轮省略，保留连续后缀；优先保留上一完整轮，如果仍不足则允许只留当前轮。

一旦省略历史，临时 SystemMessage 附加固定警告：“部分历史轮次已省略；不要将历史当作当前事实，当前状态必须重新使用只读工具核验。”警告本身计入同一个预算。工具正文和历史原文绝不拼接成 System 指令。仅当前轮仍超预算、历史无法安全切分或输入不可估算时，不调用模型或工具执行，返回“估算上下文超预算；本次诊断未完成。请使用新 Thread 或缩小输入。”之类的明确错误。Provider 真实 Context Limit 错误另行分类为诊断未完成；不回显异常原文。

决策元数据只记录状态、估算值、省略轮数和固定错误码，不记录消息正文、私有 URL、密钥或 Pod Log。无摘要游标、无第二套预算、无 AgentState 字段迁移。`/repair-demo` 不进入本组件。
