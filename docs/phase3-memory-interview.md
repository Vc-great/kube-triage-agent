# Phase 3 Incident Memory：面试口述版

## 约 75 秒

“这个 Agent 把四类信息分开：Checkpointer 保存单个 Thread 的对话和 HITL 状态；Context Window/Compaction 控制历史对话进入模型的长度；Store 保存经 Demo 审批的跨 Thread Incident Memory；Reader 本轮回执才是当前 Kubernetes 状态的证据。Memory 只引用白名单字段，`recorded_at` 是保存时间，不能替代本轮 `pods_get`，也不能授权 Repair。

我用真实 `gpt-6-luna`、正式 Aegra Graph 和合成 Mock Kubernetes 做了 12 个案例、每案例 5 次、A/B/C 三臂的 180 次配对实验。A 不读 Memory，B 读相关历史，C 读旧 UID 或冲突历史。规则初筛的 grounding 正确率是 A 60/60、B 59/60、C 59/60；B/C 输入 tokens 平均比 A 多约 1098/986，工具调用略少，但没有证据支持诊断提升。一个 B 样本在 `pods_get` 403 后达到模型决策上限，一个 C 样本被脱敏器的凭据样式规则挡下，均保留在 ITT 分母。

最有价值的失败是 HMAC 证明在第二批工具调用后被清空：工具节点类型标注过窄，只收到 `MessagesState`，丢了 `AgentState.reader_attestations`。我用 Aegra checkpoint 复现 1→0，改为 `AgentState` 并加双批次回归测试，修复前后数据分批，避免把基础设施错误当 Memory 效果。另有 OOMKilled 的 `lastState` 投影不完整和严格 Pod 句式的覆盖限制，需要后续处理。整个实验没有连接真实 Kubernetes 或 Repair；真人网页 Approve/Reject/Revoke 仍待用户手动验收。”

## 面试追问时的证据边界

- 这是 **真实模型 × 合成 Reader**，不是生产准确率。A 已接近天花板，样本彼此相关；bootstrap 区间只作探索性描述。
- B/C 最终回答出现“历史案例参考”是后端展示，不能当作模型因 Memory 推理变强。历史记录的 `user_reviewed` 在本实验只来自 `scripted_demo_approval`。
- 同名新 UID、当前 Ready 与历史 CrashLoop 冲突时，必须以本轮 `pods_get` 为准。案例 P33-03 是可讲的旧历史负例；P33-07 是 Reader 403 时不得凭 Memory 断言健康或根因的负例。
- G31-13 真人 UI、Store 非事务 CAS 风险、自然问法与 Deployment owner 检索范围、真实长上下文 Provider 压测均未被本实验完全关闭。
