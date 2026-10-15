# Issue #28 Gate B：安全动态历史摘要设计

基线：2026-10-15 重新 fetch 后 `origin/main=756c4311e21a308fd8e56178b990ffa644665f09`，即已合并 PR #29。Gate A 的 `ContextPlan`、`estimate_context()`、`_split_safe_rounds()` 是本阶段唯一预算与轮次边界。

## 数据流

1. `_llm()` 先取得四个 Reader 工具 Schema，调用 Gate A `build_context_view()`。`disabled`、`fits`、`rejected` 不触发摘要；`rejected` 明确结束诊断。
2. 仅在 `trimmed` 时，从 Gate A 已验证的完整轮次中选连续已结束的历史前缀。最靠近当前轮的一个已结束轮次和最新 Human 开始的当前轮保留原对象。摘要前缀可比 Gate A 省略前缀稍长，以给摘要留预算。
3. 源只包含这些完整轮次。对 `/repair-demo`、审批、Scale、密钥形态与伪 System 文本采用保守拒绝；源估算最多 16384 Gate A 单位，超限直接回退。摘要请求用现有 `chat_model()` 的**未绑定工具**实例，限制 512 输出 Token、12 秒超时，最多一次模型请求。提示将历史问答、日志和 Event 视为非可信数据，要求精确 JSON。
4. 摘要校验精确字段：`version=1`、`not_current_evidence=true`、1–8 条 `history_notes`，每条含一基 `round_ref`、`history_question`、`observation`、`uncertainty`。限制字段长度、总长、轮次范围与顺序；未知字段、非 JSON、工具调用、授权和危险命令文本均拒绝。自动校验不证明语义真实性。
5. 合法摘要编码为固定标签的普通 `AIMessage`，放在主 System 之后、保留轮次之前。它没有 Tool Call，不是 System、Human 或 ToolMessage。以 Gate A 同一 `estimate_context()` 重新估算 **System + 四工具 Schema + 摘要 + 保留轮次 + 当前轮 + 输出预留**；不合预算则回退原 `ContextPlan.messages`。原始 `messages` 不变。
6. 仅将成功且被送模采用的摘要写入可选 `AgentState.context_summary`；失败时仅存版本、失败固定码、覆盖边界与指纹，阻止同一当前轮重复尝试。缓存命中需核对版本、源原始消息 SHA-256、连续前缀长度、严格 Schema，并再过最终预算。失配重算或回退。新 Human 可复用旧摘要，只要原始前缀未变且当前预算仍容纳；超长新历史仍可能退化。

## 运行与安全边界

- `CONTEXT_SUMMARY_ENABLED=false` 默认关闭。开启时必须同时开启 `CONTEXT_WINDOW_ENABLED=true`。短 Thread 送模消息与 Gate A 完全一致。
- `_counts()` 和 `_has_tool_evidence()` 始终看原 State 当前轮；摘要不充当当前 Kubernetes 证据。`/repair-demo` 走原独立路由；`resources_scale` 不进入 LLM 的工具 Schema。
- 摘要模型调用发生在 `_llm()` 内；节点返回时才写 Checkpoint。摘要请求完成但节点写入前崩溃，重放允许再次请求；不承诺 exactly-once。失败回退只使用 Gate A 已验证的安全裁剪视图，绝不送超预算全量历史。
- 审计只记固定状态/失败码、调用次数、缓存命中、Provider usage（缺失为 UNKNOWN）、耗时；不记源正文、摘要正文、Pod Log、用户问题或凭据。长度和词形拦截属于保守护栏，不是通用 DLP 或抗注入的语义证明。
- 额外摘要请求有成本；首次运行的总 Token/费用可能增加。真实模型的兼容性、摘要质量、净收益仍需单独获授权的 Mock-only 实测与人工审阅。
