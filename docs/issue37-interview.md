# Issue #37 面试讲法

## 60–90 秒

此前用户只能看到最后回答和 Tool 卡，看不到 Agent 正在裁剪上下文、生成摘要、请求模型还是执行 MCP Reader。我在真实 Graph 边界生成固定词表的 `agent_progress`，通过 LangGraph Custom Stream、Aegra SSE 的 `custom` 事件传给 React SDK 的 `onCustomEvent`，再放进独立的可折叠 Timeline。正常 AIMessage、ToolMessage 和审批 UI 仍走原有通道。

难点是协议和可信状态：先用真实 Aegra Run 证明 `custom` 与 `values` 并行工作，再处理 Tool 的 started/failed/completed 与原 `tool_call_id` 配对、事件 UUID 去重、Thread 隔离和刷新后的临时状态。Context Summary 的内部模型调用用 `nostream` 隔离，Content Blocks 只抽文本并继续严格校验；失败回退 Gate A。进度文案来自服务端白名单，不能混进 Pod 日志、Tool Result 或模型推理。Repair 的 interrupt/Resume 仍是审批权威，Timeline 不产生写权限。

## 追问

**为什么不用 `messages` 放进度？** 它会污染聊天历史、Checkpoint 和模型上下文，还可能把内部 JSON 当回答。`custom` 专门承载短暂 UI 进度，正文保持原语义。

**SSE 重放或两次 Run 怎么办？** 同一 `event_id` 幂等，提交新 Run 和切换 Thread 清空内存，并检查事件 `thread_id`。当前 Custom payload 没有可靠 Run ID，故同 Thread 并发或断线晚到事件仍有边界，不能把 Timeline 当权威审计。

**刷新后为什么 Timeline 消失？** V1 是 ephemeral。正式 AI/Tool/审批历史从 Checkpoint 恢复；过去的进度无法证明还能准确重建，因此不回放。

**HITL 会不会因为进度而绕过审批？** 不会。进度仅在只读诊断路径埋点；Repair 沿用原 interrupt、proposal ID 验证和执行前重查。离线模拟中拒绝审批后没有写入。
