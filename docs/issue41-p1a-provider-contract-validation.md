# Issue #41 P1-A CPA / gpt-6-luna Provider Contract Gate

本报告对应 [P1-A 权威方案](plans/issue-41-p1a-cpa-gpt6-luna-provider-contract.md)，仅覆盖 P1-A。Planning PR [#58](https://github.com/Vc-great/kube-triage-agent/pull/58) 已合并，实施时实时 `origin/main=371715551911f713df3ec2d6dce62eed51fcf6f4`。独立 AO Worktree：`provider-contract-3`，分支：`ao/provider-contract-3/p1a`。最终交付 Head、CI 和独立 Reviewer 以 Implementation PR 正文为准，不把报告文件自身的提交 SHA 循环写入文件。

**当前结论：离线实现可审查；真实 CPA Contract 为 BLOCKED。真实 CPA 请求数为 0，不能声称模型支持 Tool Calling，也不产生 P1-B GO。** 用户已批准本轮有限合成探针，不需要逐笔费用审批；阻塞原因是配置/安全出口，非费用授权。

## 实现与偏差

新增 `scripts/issue41_p1a_probe.py`，不加载 Graph、不执行 Reader、不读取 dotenv、不载入冻结 R01/R05。仅固定三步：人工合成中文文本 → `pods_get`（`kube-triage-demo/p1a-synthetic-pod`）→ 配对 ToolMessage（`p1a-fake-uid`）续答。工具 Schema 复用原 Reader Schema 构造器，参数复用 `validate_call` 后再限制为精确假 Pod；没有 Kubernetes 调用。

冻结锁定 SDK：`openai==3.29.0`、`langchain-openai==1.7.0`、`httpx==0.28.1`。显式 Chat Completions / `use_responses_api=False`、`max_retries=0`、非流式、输出 1024；HTTP transport `retries=0`、`trust_env=False`、`verify=True`，Client 不跟随跳转。真实请求前逐字典比较 SDK 实际发送体与固定合成序列；模型名、工具参数、路径或正文变化均拒绝。每次发送前预约，单进程最多 24 次、600 秒、单次 45 秒，串行；错误锁存 STOP，无自动变体、补跑或 Responses 回退。

新入口默认不联网。唯一秘密输入为进程环境 `CPA_API_KEY`；`--endpoint` 要求用户明确批准的完整 Chat Completions URL。URL 禁 userinfo/query/fragment/编码路径/非规范写法；远端只接受 HTTPS，HTTP 仅精确 `127.0.0.1` 或 `::1` 且显式端口。父进程只把白名单环境与注入 Key 交给 OS 隔离子进程，移除继承 proxy/telemetry 配置；SDK tracing 显式关闭。

**已发现的 OS 限制与设计偏差：**此机 macOS `sandbox-exec` 的 `(remote ip "数字IP:端口")` 实测报 `host must be * or localhost in network address`。不能将其降级为 `*:443`。因此当前 launcher 对远端 HTTPS 一律 BLOCKED；不 DNS 探测、不发送 Key。只实现已验证的 `localhost:明确端口` TCP OS 白名单，应用层再固定为批准的 `127.0.0.1` 或 `::1` 地址和完整路径；该 OS 规则本身覆盖两种 loopback 地址，**不是单地址 OS 防火墙**。loopback 网关的上游转发和账单仍不可观察。远端支持需要可核验的精确出口机制后再审查，不能通过额外配置字符串或确认开关绕过。

私有输出复用 P0 `PrivateOutput`：全新目录 0700、独占文件 0600、拒绝符号链接和覆盖。只记录白名单 Usage、HTTP 状态、已知模型回显（不符记 MISMATCH 并保留摘要）、finish_reason、ID/请求 SHA256、脱敏合成回复、工具参数、SDK Usage 比对和延迟；不存原始 HTTP body、Authorization、任意响应头或错误内容。stdout 仅输出状态、停止原因、计数与 UNKNOWN/NOT RUN 元数据；全部行级证据与回复正文只写私有文件。协议通过单列 `protocol_status=PASS`，语义状态始终 UNKNOWN、人审 NOT RUN，整体状态在无人审时为 UNKNOWN；固定短语检查不能证明自然语言语义正确，同义“故障已经解决”也不会获得语义 PASS。缺失 Usage 保持 UNKNOWN，不填 0；上游重试、模型实际版本、隐藏账单和成本始终 UNKNOWN。单进程限制不是费用上限，也不是跨多次人工启动的全局账本；本 Worker 没有执行真实重启或补跑。

## 实测证据

环境：2026-10-20，macOS arm64，CPython 3.13.14。先核对 Host 已有 Runtime/缓存，再 `uv sync --frozen --offline --python 3.13`；没有下载、升级依赖，没有启动 Compose 或稳定环境。

- Ruff：`server/.venv/bin/ruff check` 覆盖当前 CI Python 文件集，并新增 P1-A 脚本；PASS。
- 专项：在 `server/` 执行 `.venv/bin/python -m pytest -q tests/test_issue41_p1a_probe.py`：49 passed。除显式 loopback OS 测试外均为 MockTransport；OS 子进程端到端仅连本测试新建的合成 HTTP 服务，3 次假响应，不是 CPA/真实模型。
- 负测：301/302/307/403/429/500/503、断连、超时、坏 JSON、模型回显不符、finish_reason、Usage 缺失、未知工具、跨 Namespace、其他 Pod、空 Tool ID、恶意正文附合法工具、24 次耗尽、并发、600 秒熔断、错误后 STOP、其他 URL/请求正文、默认 CLI/缺凭据零 DNS；PASS。
- OS 出口：合成子进程允许指定 loopback TCP 端口，另一个本任务临时端口 EPERM；0700/0600 与 Key 不落盘检查 PASS。远端精确 IP 规则的首次实测 FAIL，已改为明确拒绝远端启动；不把这个 FAIL 隐藏为远端可用。
- Manifest：`.venv/bin/python ../scripts/check_issue11_manifests.py`：3 个 Pod manifest PASS。`eval/`、正式 `server/src`、SDK lock、Graph 和旧脚本与基线无差异。
- macOS OS `(deny network*)` 内执行原 `--dry-run`、`--offline-readiness --simulate-budget`、P0 `--offline-contract --simulate-budget`：全部 PASS；24 离线槽、4 离线槽/12 模拟 HTTP、4 离线槽/12 模拟 HTTP。P0 `live_gate=BLOCKED` 保持。相同 OS 禁网策略下新 CLI 默认 BLOCKED，零发送。
- 全量 pytest：631 passed in 55.25s（46 项专项版本）；随后协议检查增补至 49 项，最终专项 49 passed in 3.39s；成功/失败子进程均验证 stdout 不包含回复和证据行。CI 和独立 Reviewer 最终结果见 PR 正文；未取得结果前不宣称 PASS。

独立 Reviewer 首轮提出两项必改（无证据同义结论的 Gate 标注、私有证据打印 stdout），已分别修复并补充回归；最终 Head 的复审结论以 PR 正文为准。初始 Head CI Python/Web/Compose 全部 PASS，Python `630 passed, 2 skipped`；macOS 专项不适用于 Linux，不能把 skipped 当作 Linux PASS。

## Gate 与停止边界

| Gate | 状态 | 证据/限制 |
| --- | --- | --- |
| #58 合并、实时基线、隔离范围 | PASS | merge SHA 等于实施时 main；只改新 CLI、专项测试、CI lint 文件集及本报告 |
| L0 原离线行为 | PASS | OS 全禁网运行；原脚本不改，P0 仍 BLOCKED |
| L5 Mock 负测与本机 loopback OS 策略 | PASS | 49 项专项；仅假 Provider，禁止解释为 CPA 合约证据 |
| 远端精确 IP OS 白名单原型 | FAIL | Seatbelt 不接受该语法；launcher 对远端 fail closed |
| 安全配置与唯一真实 CPA 出口 | BLOCKED | Host/Worker 均未发现 CPA/OpenAI/LLM 注入；用户尚未提供非秘密 endpoint/安全注入方式；远端 egress 机制不足 |
| L1 文本 / L2 Tool Calling / L3 ToolMessage | BLOCKED | 真实模型请求 0；未收到任何 CPA HTTP 回包 |
| L4 UID 冲突/403 真实合成负测 | NOT RUN | 可选探针，L1–L3 未成功，不追加请求 |
| 真实 Usage / 模型回显 / 延迟 | UNKNOWN | Mock 值不是真实值 |
| 上游内部重试 / 账单 / 实际费用 / 模型版本 | UNKNOWN | 客户端限制不能证明 CPA 内部行为 |
| B8、P1-B 四槽 / P2 Formal / 真实 K8s / 真人盲审 | NOT RUN | P1-B/P2 未授权；没有 GO 或质量结论 |
| Ruff、全量 pytest、CI、独立 Review | 逐项见 PR | 不以专项通过替代未完成项 |

继续真实探针需要用户提供非秘密 CPA 完整 Host/Port/Path 与私有注入渠道（Key 不进聊天/PR），以及满足该端点的可验证出口限制。未解决时保持 BLOCKED，不搜索 `.env`、Keychain、历史秘密或真实集群数据。若最终 CPA 是远端 HTTPS，当前 launcher 会拒绝；不得仅为执行成功删除 OS Gate。

回退：停止独立 CLI 或回滚此 PR；无服务、数据、Checkpoint、Repair/Memory 或部署迁移。Issue #41 保持 Open，Draft PR 不自动合并，历史 FAIL 和 B2/B3 状态保持。
