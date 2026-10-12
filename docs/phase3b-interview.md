# Phase 3B 面试口述问答

1. **什么触发真实写入提案？** 代码：`graph.py:_route`。原理：精确命令路由。原因：自然语言诊断和模型输出不能构成授权。追问：用户说“请修好它”会怎样？
2. **为什么提案在审批节点前生成？** 代码：`graph.py:_repair_prepare`。原理：节点完成后 checkpoint 保存 ID。原因：`interrupt()` 恢复会重放审批节点，ID 必须稳定。追问：在审批节点里调用 `uuid4()` 有何问题？
3. **HITL 怎样挂起？** 代码：`graph.py:_repair_approval`。原理：`interrupt()` 把提案交给 Aegra Thread。原因：等待人的结构化决定。追问：聊天文本“approve”能恢复吗？
4. **Resume 怎样防跨 Thread？** 代码：`graph.py:_repair_approval`、`repair-approval.tsx`。原理：当前 checkpoint 的提案 ID 与回传 ID 必须一致。原因：过期或伪造决定不得执行。追问：若只校验 `decision` 会怎样？
5. **为什么审批节点不调用写工具？** 代码：`graph.py:_after_repair_approval`、`_repair_execute`。原理：批准后才经条件边进入执行节点。原因：避免 `interrupt()` 前或重放时副作用。追问：节点重放仍可能造成什么风险？
6. **模型怎样被隔离？** 代码：`graph.py:_llm`、`mcp_client.py:_allowed_tools`、`repair.py:_scale_tool`。原理：Reader 与 Repairer 两个不同 MCP 客户端和身份。原因：模型只能看四个只读工具。追问：模型建议扩容为何仍不可执行？
7. **为什么 RBAC 是 get/update？** 代码：`repair-rbac.yaml`、上游 v0.0.67 `ResourcesScale`。原理：先 GET scale，再 UPDATE scale。原因：与实际调用一致，不授予 patch。追问：`resourceNames` 是否足以确认归属？
8. **为何额外 GET Deployment？** 代码：`repair.py:read_deployment`、`validate_deployment`。原理：Scale 对象不携带 Deployment 标签。原因：检查项目标签、模板、UID。追问：同名资源被删后重建怎样发现？
9. **如何处理重复 Resume？** 代码：`graph.py:_repair_execute`。原理：写前重新 GET，已为 1 则 no-op。原因：降低重放重复写风险。追问：为何不能承诺 exactly-once？
10. **写超时后可否重试？** 代码：`repair.py:write_scale_once`、`graph.py:_repair_execute`。原理：响应丢失时状态不确定，回查但不重试。原因：避免多次危险写。追问：回查为 1 能证明本次调用成功吗？
11. **副本到 1 是否等于 Pod Ready？** 代码：`repair.py:pod_readiness`。原理：控制面期望值与 Pod 条件分离。原因：镜像拉取、调度或探针仍可能失败。追问：报告中哪三种结论需要区分？
12. **为什么不能直接修 CrashLoop/OOM？** 代码：`prompts.py:SYSTEM_PROMPT`、`docs/phase3a-report.md`。原理：诊断证据不足时不能断言根因。原因：Phase 3A 人工 grounding 曾扣分；本 Demo 只演示 0→1。追问：需要什么额外证据才可建议根因修复？

## Gate B 真实观察补充（2026-10-12）

13. **真实 RBAC 与静态 Role 有什么不同证据？** 本轮用实际受限 Repairer kubeconfig 验证目标 scale `get/update` 和 Deployment `get` 为 yes，跨 Namespace、其它目标、Pod 写、Secret 读及 Reader scale update 为 no。`kubectl auth can-i` 是权限判定，不能代替真实写结果；本机 kubectl 用 `TYPE/NAME --subresource=scale` 指定资源名。
14. **真实零副本 Scale 为何需要特殊解析？** `v0.0.67` 实际 GET 在 0 副本时返回 `spec: {}`、`status.replicas: 0`。原解析器拒绝缺失 `spec.replicas`，Graph 因而不能生成提案；修复仅对明确的零值响应补 0，异常响应仍拒绝。
15. **为什么写后 Graph 说 Ready 未知，而集群 Pod 已 Ready？** Reader MCP 实际 Pod 列表是顶层 YAML 序列，原解析器只识别带 `items`/`pods` 的对象。修复后用同一真实 Reader 只读回查为 ready；本轮同一 Thread 的历史结果仍保留当时的 unknown，不篡改历史。
16. **人工点击和严格 Gate 流程如何区分？** 用户确认亲自点击网页 Approve，审计将 `repair_decision`、一次 `repair_scale_call` 和 `repair_result` 关联到同一 Thread，控制面与 Pod 回查均为 1。但该 Thread 是 Codex 在 B05 检查中创建/输入命令，未满足 B06 的“用户本人新建并输入”步骤；不能为了补流程再写一次。
17. **为什么不宣称 exactly-once？** 应用审计观察到一次写调用及回执，但 `resources_scale` 是 GET→UPDATE，存在并发竞态；外部写入来源、响应丢失和重放边界不能靠单次回查完全排除。答题时分别报告 `write_attempted`、`write_response_received`、Scale/Deployment desired 与 Pod Ready。
