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

## 续测：按主工作树 `.env` 参数执行（同日）

用户指出其本地测试通过，并明确同意在测试网络使用 `.env` 的私有 HTTP 地址传输合成数据及 API key。重新核对发现：此前 `gpt-6-luna` 测试配置与 `.env` 的**模型名、API key 相同**，但端点不同，且此前开启 `EVAL_LUNA_RESPONSES_HIGH=true`，`.env` 未设置该项。先前连接失败不能证明 `.env` 配置不可用。本次在 Host 验证该端点可达；它经普通网络接口、非回环，原端口不支持经证书验证的 TLS。这个明示授权只适用于本次测试网络续测，不改变仓库默认的传输约束或先前验收结论。端点、密钥和认证头均未写入证据。

固定范围：`gpt-6-luna`，`.env` 中的模型名、地址、API key；`TRIAGE_ENV=test`、`EVAL_LUNA_RESPONSES_HIGH=false`、`REPAIR_ENABLED=false`。唯一 MCP 是本机 `127.0.0.1:8000` 的静态 `issue12-blind-v1` Mock，四个只读工具，无真实 Kubernetes 连接或写入。摘要最多 512 输出 Token、12 秒，诊断回答各最多 1024 输出 Token。用户批准最多 8 次真实模型请求、合计 80k 输入及 8k 输出 Token；实际执行 **7 次逻辑请求**，其中 6 次成功、1 次摘要超时。成功请求回执合计 **7247 输入、695 输出 Token**；超时请求的实际 Provider 用量及费用均 **UNKNOWN**，不能据此声称总费用为零或精确总用量。没有再发请求。

Smoke：1 次标准工具绑定请求，约 2.94 秒，回执 660 输入 / 29 输出 Token；模型正确发出 `pods_get`，Mock 返回 `static-fixture`，**PASS**。

| 配对场景 | Gate A Trim | Gate B Summary | 当前事实与边界 |
| --- | --- | --- | --- |
| 10 个合成历史轮次，同一当前 `sample-a` Mock 证据 | 裁剪 7 轮；诊断请求 1382 输入 / 81 输出 Token，4.4 秒 | 计划覆盖 9 轮；摘要在 12 秒超时、usage UNKNOWN，按 Gate A 安全回退；后续诊断 1382 输入 / 129 输出 Token，4.5 秒；整侧 16.5 秒 | 两侧均识别 `Running`、容器未就绪、`CrashLoopBackOff`、重启 4 次；旧 UID 哨兵未进入答案，未臆断崩溃原因。摘要质量 **BLOCKED**，回退 **PASS**。 |
| 3 个较长合成历史轮次，同一当前 `sample-a` Mock 证据 | 裁剪 1 轮；诊断 1421 输入 / 79 输出 Token，4.8 秒 | 有效摘要覆盖 2 轮；摘要 969 输入 / 219 输出 Token，5.6 秒，诊断 1433 输入 / 158 输出 Token，5.8 秒；整侧 11.4 秒 | 两侧识别同样当前事实、不引用旧 UID 哨兵、不臆断根因；摘要结构被接受，**L3 路径 PASS**。 |

三轮场景的 Gate B 单次诊断估算输入由 Gate A 的 6475 降至 6073（均含固定输出预留），但真实诊断输入由 1421 升到 1433；加上摘要，Gate B 成功回执共 2402 输入 / 377 输出 Token，高于 Gate A 的 1421 / 79。此样本没有净 Token 或费用收益。十轮场景的超时可能仍产生 Provider 侧费用，无法精算。两组只有各一次配对，当前事实核对只是有限人工检查，不能推广为模型质量或性能结论。Aegra SSE/UI、真实 Kubernetes 与独立正式 Review 仍 **NOT RUN**；Draft PR 保持 Draft。

可重复的本地续测脚本及脱敏原始指标位于忽略目录 `.local/eval-runs/issue28-gateb-live-20261015/`，没有密钥。Mock 监听在续测后已停止。
