# Phase 3A 面试问答

下面的结果来自本轮离线测试或真实模型 Smoke；完整 12 次数据见 `phase3a-report.md`。这里的真实模型指实际 LLM + Mock MCP，不是真实 Kubernetes。

1. **Agent 测试比传统软件难在哪里？Fake Model 能测什么？** 传统函数给定输入通常有稳定输出；Agent 会自己选工具、决定轮数，结论还要核对证据。`server/tests/test_phase2.py:FakeModel` 能验证 Graph 路由、调用配对、预算和安全拒绝，不能证明真实模型会选工具。本轮 Fake 回归在 43 项 pytest 中通过，而真实 Smoke 在 `scripts/eval_phase3a.py` 中实际产生 4 个 Tool Call。追问：如果 Fake 全通过、模型没发 Tool Call，效果 Gate 应判失败。

2. **怎样建立 Golden，为什么问题不能透露答案？** 在 `eval/cases.json` 独立保存标签、必要证据与禁止断言；问题只要求调查目标 Pod。答案泄露会把评测变成照抄。实际四项 Golden 的问题都不含预期标签，`server/tests/test_phase3a.py:test_golden_is_neutral_and_complete` 已检查。追问：Pod 名仍带场景暗示，所以只能称小样本 Demo。

3. **Tool Call 正确率、根因准确率、证据 grounding 有什么区别？** `scripts/eval_phase3a.py:inspect_messages` 分别核对调用协议、合法参数和目标证据；诊断与 grounding 由人工填 `reviews.json`。实际 CrashLoop Smoke 四个 ID 一一配对、工具成功 4 次、证据充足；这本身不自动给诊断 1 分。追问：工具成功不等于选对工具，更不等于结论正确。

4. **健康样本能衡量什么？误报率怎么算？** `eval/cases.json:healthy` 与 `score_reviews` 用健康三次中误报明确故障的次数除以 3。实际 Mock 的 `healthy-pod` 为 Running、容器 ready、重启 0，Namespace 同时有其它 Pod 的 Warning；`test_phase3a.py` 验证了该混合事件。追问：Running 也不能证明业务健康。

5. **为何 Namespace Event 不能直接证明目标 Pod 异常？** `mock_mcp.py:events_list` 只按 Namespace 调用；每条 Event 的 `involvedObject.name` 才是归属。实际离线测试看到四个 Pod 的 Event 同时返回，健康 Pod 自身只有 Normal；`inspect_messages` 不把其它 Pod 的 Warning 算为目标证据。追问：若模型在报告里错归事件，人工 grounding 要扣分。

6. **Running + CrashLoopBackOff 矛盾吗？OOM 与 137 呢？** `fixtures/crashloop.json` 的 Pod phase 是 Running，容器 `state.waiting.reason` 是 CrashLoopBackOff；两层状态不同。`fixtures/oomkilled.json` 有 `lastState.terminated.reason=OOMKilled`，`exitCode=137` 只是伴随字段。实际 43 项测试核对了这些字段；单凭 137 不能断言 OOM。追问：当前容器可已重启 Running，同时保留上一次 OOM 终止记录。

7. **ImagePull 没日志时怎么办？** `mock_mcp.py:pods_log` 对 `imagepull-pod` 返回 `available=false, logs=null, reason=container has not started`；判断主要靠 `pods_get` 等待原因和归属明确的 Failed Pull Event。离线测试实际调用可选 `tail/container` 并确认无日志。追问：不能把“无日志”解释成“无故障”，也不能编造运行日志。

8. **为何不用中文关键词自动判准确率？人工 rubric 与 LLM Judge 各有何取舍？** 同一句“可能 OOM”可能是有据的保留判断，也可能是猜测；字符串匹配看不到 ToolMessage。`score_reviews` 只计算人工已填写的 0/1/2，实际未填时返回 PENDING。人工可引用证据但耗时；LLM Judge 可扩展却会引入另一个模型偏差与成本，本 Demo 不加。追问：评分人要同时看报告句子和对应工具 ID。

9. **三次结果不同怎么定位？** 先在 `scripts/eval_phase3a.py` 的逐条记录看 Run 状态、模型决策数、工具协议、目标证据、用量和耗时，再读私有 `*-evidence.json` 的本次 Thread。实际 Smoke 为 3 次模型决策、4 次工具、证据充足；后续三次基线的差异详见报告。追问：同一问题只挑最佳一次会高估质量。

10. **12 次能支持什么结论？** 能说明这四个固定合成场景里，当前模型与提示词的工具选择、证据引用和波动；不能外推到真实集群的噪声、权限、日志规模。`eval/cases.json` 只有四类，`scripts/eval_phase3a.py:summarize` 保留 12 个计划分母。实际 Smoke 只证明一条真实调用链，完整 12 次与失败均在报告中。追问：下一步应增加独立场景和盲样，而非改 Golden 迎合模型。
