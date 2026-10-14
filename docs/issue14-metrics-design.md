# Issue #14：离线 Metrics v1 设计

## 数据边界

`scripts/eval_metrics.py` 只读取既有 `.local/eval-runs/<目录>/runs.json` 与逐 Run 私有证据；不读取 `.env`，不连接 Aegra、Provider、MCP、Compose 或 Kubernetes。输出必须是本工作树 `.local/eval-metrics/issue14-<新 ID>/`，目录 0700、文件 0600。`metrics.json` 含内部 Thread/Run ID，仅留私有目录；`report.md` 只含匿名聚合，可人工复制到文档。历史 Runner、Golden、Fixture 和旧 JSON 不改。

两个版本适配器：Phase 3A 读取 `<case>-<repeat>-evidence.json` 的 `messages`；Issue #12 读取 `<arm>-<case>-<repeat>-private.json` 的最终 `state.values.messages`。History 仅作为历史证据保留，不与 State 或 SSE 累加。数据源缺失时该 Run 保留记录、指标为 null 与 `missing_reasons`，不会从旧报告数字反推轨迹。

每个数值采用 `{value, unit, denominator, provenance, status, reason}`；未知用 null 和原因。`source_record_present` 与 `source_measurement_present` 分开。模型 ID 优先响应元数据，只有配置时标 `configured`。`run_status` 保留 Runner 判定；`protocol_status` 保留 Aegra 状态；工具失败另列，人工 `diagnosis_correct` 未经已核验逐条评分关联为 UNKNOWN。`real_k8s` 本期 NOT RUN。

## Token 与工具

仅 `name=triage_llm` 的真实模型 AIMessage 进入 Token 统计；Graph fallback、ToolMessage 均排除。每条消息优先 `usage_metadata`，备选 `response_metadata.token_usage`，两者不相加。每个字段独立记录 observed/derived/unknown；input+output 可派生 total，Provider 三项不一致保留 `inconsistent`。缺失从不补零。稳定消息 ID 去重；缺 ID 或相同 ID 冲突使 Run 用量不完整。缓存读取与 reasoning 子类保留原始字段语义，已计入主 Token 时不再加总。

`tool_requests` 来自 AIMessage Tool Call，`tool_messages_received` 来自 ToolMessage；唯一 ID 一一配对后才分类。`unknown_or_unpaired` 保留缺失、错配和重复记录。配对响应分为 `wrapper_success`、`wrapper_error`、`policy_rejected`、`budget_skipped`、`unknown`；外层 success 内层 `ok=false` 算失败，外层 error 内层 `ok=true` 算协议冲突。`mcp_transport_attempts` 没有带 tool_call_id 的服务端 trace，一律 UNKNOWN。分母分别为 `tool_requests`、`matched_tool_responses`，分母零时比率 null。

正文结构检查仅识别 JSON/YAML 对象或列表、明显非法内容；无法可靠证明的内容为 UNVERIFIED。即使结构 VALID，也不证明字段语义、Pod UID 归属或诊断正确。Issue #13 G03 仍为 PARTIAL FAIL，L3 真实模型对抗 NOT RUN。

## 时延与成本

Runner `elapsed_seconds` 是 `time.monotonic()` 端到端区间，包含 Thread 创建、Run/SSE 及后续 State/History 取证。P50=`statistics.median`；P95=排序后第 `ceil(0.95*n)` 个，即 nearest-rank，与线性插值不同。所有 Run、成功 Run、失败 Run 分别统计；n=0 为 null，n<20 标 `LOW_SAMPLE_WARNING`。任何样本数均不作为生产 SLO。缺少可关联 tool_call_id 的阶段时间戳时模型/MCP 耗时 UNKNOWN。

估算价格必须由用户或 Provider 提供可复核快照，至少含 `provider`、`billing_entity`、`model_deployment`、`currency`、`unit=per_1m_tokens`、`input_uncached_rate`、`input_cached_rate`、`output_rate`、`effective_at`、`source_checked_at`、`source_url_or_document`、`assumptions`，可加 `effective_until`。运行记录还必须可验证 Provider、部署、币种、运行时间与隐藏重试账单口径；输入/输出及差价缓存量完整才估算。否则 UNKNOWN。私有 CPA/兼容 Provider 不能套公开零售价格；Token 用量不等于账单金额。单次 `estimated_cost` 永远不是 `actual_billed_cost`。

## CLI

```bash
python3 scripts/eval_metrics.py --source .local/eval-runs/<既有目录> --dataset issue12-blind-v1 --dry-run
python3 scripts/eval_metrics.py --source .local/eval-runs/<既有目录> --dataset issue12-blind-v1 --out .local/eval-metrics/issue14-<新 ID>
```

`--dry-run` 仅检查路径、`runs.json` 格式和记录数，不建目录、不读价格快照、不写文件。输入限本项目 checkout 的 `.local/eval-runs`；输出限当前工作树的新 `.local/eval-metrics/issue14-*`，拒绝 symlink、路径逃逸、覆盖和交叠。输入单文件大小与 Run 数有上限。示例价格如用于测试均属虚构，不可作为实际账单。
