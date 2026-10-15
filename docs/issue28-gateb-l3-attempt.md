# Issue #28 Gate B：获批真实模型 Smoke/A-B 尝试

日期：2026-10-15（Asia/Shanghai）。用户已授权使用真实模型、合成数据与 Mock MCP。本补充记录不修改 [此前离线验收](issue28-gateb-validation.md) 的历史快照。代码 Head 起点 `19a6bdcc313e30e7f97b1a4e058b9dd2537d3bd8`；Draft PR #30。

## 执行范围与数据

只使用 `TRIAGE_ENV=test` 下 Issue #12 的静态 `sample-a` Pod fixture、合成提问和四个只读 Mock MCP 工具。未连接真实 Kubernetes Reader，未执行 K8s 写入或 `resources_scale`，`REPAIR_ENABLED=false`。Mock MCP 先短暂按模块默认绑定 `0.0.0.0:8000`，随即停止并改为 `127.0.0.1:8000`；`tools/list` 返回预期四工具，`pods_get(sample-a)` 返回静态 Mock 标记。评估结束后回环监听进程已停止。本轮未启动 Compose，也未创建容器或卷。

原计划：先一次兼容性 Smoke；通过后对同一合成长历史做 Gate A Trim 与 Gate B Summary 配对，固定模型、工具 Schema、数据和预算。Smoke 未取得一次成功模型生成，因此 A/B **NOT RUN**。除了正常的模型 API 认证，没有发送真实 Pod 日志、Kubernetes 凭据或生产数据。

## 模型与传输诊断

私有配置文件中的密钥只在进程内读取，未写入仓库或输出。所有候选 Provider URL 均为 HTTPS，沿用 SDK 的证书校验；未关闭 TLS/CA。端点地址与凭据不进入本报告。

| 候选 | 最小检查 | 生成尝试 | 结论 |
| --- | --- | --- | --- |
| `gpt-6-luna`，既有测试配置 | Host 代理入口可达；目标域名直连 DNS 失败，匿名 HTTPS 探测失败 | 1 次 Graph Smoke 得到“诊断未完成”兜底且无 usage；1 次最小工具绑定调用抛 `OpenAIConnectionError` | **BLOCKED：模型端点连接能力**，不是凭据无效的证据 |
| `deepseek-flash`，既有测试配置 | 匿名 HTTPS 返回 401；带现有凭据的 `/models` 返回 200，配置模型在列表中 | 禁用 SDK 重试后两次合成生成，分别在 20 秒和 60 秒抛 `OpenAITimeoutError` | **BLOCKED：生成请求超时**；模型列表可读不等于生成可用 |

共 **4 次逻辑生成尝试，0 次可核实成功回复**。前两次 `gpt-6-luna` 走仓库适配层，配置允许 SDK 最多一次重试；其底层 HTTP 尝试数 **UNKNOWN**。后两次 `deepseek-flash` 明确 `max_retries=0`，第二次还限 32 输出 Token。另有 Mock MCP 只读探测与两次认证模型列表读取，均非生成请求。

## 结果与停止决定

- Mock MCP 本机四工具发现与静态回执：**PASS**。
- 真实模型 Smoke：**BLOCKED**；没有成功生成、Tool Calling 兼容性或摘要质量证据。
- Gate A/B 真实模型配对、人工事实评分、Aegra SSE/UI、真实 Kubernetes：**NOT RUN**。
- Provider `actual_input_tokens`、`summary_input_tokens`、`summary_output_tokens`、实际费用：**UNKNOWN**。两次超时的观察等待约 20 秒和 60 秒，不是成功 Run 延迟；不能推断费用为零。
- 停止后没有继续重试、切换到不受保护的 HTTP 端点或使用真实集群数据。Draft PR 保持 Draft。若继续，需要一个可完成生成的 HTTPS 端点或本机回环代理，并重新固定模型、请求上限及 A/B 样本；不把本轮失败包装成 L3 PASS。
