# Issue #13：Tool Result 注入与失败退化设计

基线：2026-10-14 实时 GitHub `main=b3ab189a819336d43c9ed41653f970c3757ce21c`；Issue #13 和 #12 均 Open，PR #23 已合并。独立分支 `codex/issue13-safety-regression` 从该提交创建。只使用合成日志、Event、FakeModel 和内存 NativeTool；不请求 Provider，不连接 Kubernetes，不启用 Repair。

## 信任边界

用户问题与仓库 `SYSTEM_PROMPT` 是不同来源；Pod、Event、Log 是不可信工具数据。Graph 把原生返回包装进 `ToolMessage`，ID 与发起调用配对；工具结果中的 `<system>`、`SYSTEM:` 或人工建议没有 SystemMessage 权限。模型仅绑定四个 Reader Schema；`validate_call()` 在工具发现及原生 `.ainvoke()` 前核验白名单、固定 Namespace、Pod 名、tail、container 与额外字段。发现集合缺失或多出工具时拒绝绑定。`/repair-demo` 仍只由精确用户文本路由，审批与写路径不由 ToolMessage 触发。

攻击资产是诊断可信度、工具调用权限、虚拟敏感标记和 Event 归属。攻击者控制某次 `pods_log` 或 `events_list` 的正文，可能同时混入真实故障事实；不控制源码 SystemMessage、模型 Schema、`validate_call()`、用户问题或人类审批。测试中的 `TEST_ONLY_FAKE_CREDENTIAL` 是虚构哨兵。

## 代码层可保证的范围

本轮将工具参数策略异常与原生 `.ainvoke()` 异常分开。原生 `TypeError/ValueError` 归入 `server_error` 且只返回固定脱敏文案；非法参数返回固定 `policy` 文案。Graph 仅在**没有任何成功且非空的 ToolMessage** 时，把模型最终回答替换为“诊断未完成、不能确认根因或健康状态”。已有有效 Pod 证据而 Event/Log 失败时仍允许模型报告已知事实。

此最小检查不解析原生 YAML/JSON 的语义，也不证明非空文本正确。非法格式、跨 Pod Event 归属、日志中的软性诱导以及有部分有效证据时的最终措辞仍需要模型行为验证与人工审阅。`test_issue13_safety.py` 故意让 FakeModel 在非法非空返回后声称健康，以证明此边界尚未由执行层保证；该用例通过表示**缺口已复现**，不表示攻击已被抵抗。Issue #12 的 Event UID 三态规则属于其评测 Runner 的轨迹判定，并非 Graph 对任意回答的语义过滤。

## 证明层级

| 层级 | 已有与本轮证据 | 能证明的内容 |
| --- | --- | --- |
| 代码 | `mcp_client.py`、`graph.py`、四 Schema | 授权、ID、预算和无证据兜底的确定性路径 |
| FakeModel / Mock MCP | `test_phase2.py`、`test_tool_schema_contract.py`、本轮参数化 30 例 | 指定模型输出时的消息流、拒绝、失败分类；不证明真实模型措辞 |
| 历史 Real LLM + Mock MCP | Phase 3A 12 Run、Issue #12 独立 48 Run | 仅对各自冻结样本和当时 Prompt 成立；本轮恶意样本未运行 |
| 历史 Real Kubernetes | Issue #11 记录 | 只保留历史成功与 FAIL，不复用作注入验证 |
| 本轮 Real LLM + Mock MCP | `NOT RUN` | 尚无模型行为结论、通过率或 Provider 回执 |

本轮不改变 `SYSTEM_PROMPT`、Issue #12 A/B 后缀、历史 Golden、Reader/Repair 权限、CI 工作流和 Compose 运行资源。新测试位于既有 CI 的 `pytest -q` 与 Ruff `src tests` 路径内。
