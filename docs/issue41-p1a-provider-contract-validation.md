# Issue #41 P1-A CPA / gpt-6-luna Provider Wire Contract Gate

对应 [P1-A 权威方案](plans/issue-41-p1a-cpa-gpt6-luna-provider-contract.md)。Planning PR [#58](https://github.com/Vc-great/kube-triage-agent/pull/58) 已合并；实施/续作实时 `origin/main=371715551911f713df3ec2d6dce62eed51fcf6f4`。独立 Worktree `provider-contract-3`，分支 `ao/provider-contract-3/p1a`。最终交付 Head、CI 和独立 Reviewer 见 [Draft PR #59](https://github.com/Vc-great/kube-triage-agent/pull/59) 正文。

**真实结果：宿主机直连 CPA 成功；L1 文本、L2 标准 Tool Calling、L3 配对 ToolMessage 续答的有限合成 Wire Contract 均 PASS。3 次客户端 HTTP 尝试全部 200，回显均为 `gpt-6-luna`，原始 Usage 与 SDK Usage 均 MATCH。** 这不是诊断语义质量或 P1-B GO；运行摘要仍保留整体/语义 UNKNOWN、人审 NOT RUN，B8 NOT RUN。

## 授权与执行范围

用户后续明确允许从现有 `.env` 在进程内使用配置，并指定 `http://192.168.31.110:8317/v1`。该指令构成仅此 IP、8317 端口、`/v1/chat/completions` 路由的明文 HTTP 例外，不推广到其他远端 HTTP。最新用户确认宿主机可直接请求该地址，要求继续模型测试，本轮据此启动一个新的运行标识。未使用本机 7890 代理；中断前未提交的代理草稿已撤回，真实运行使用原已批准源码。

只解析 `.env` 所需配置，不输出、复制、上传文件内容或 Key，不修改 `.env`。加载器仅向父进程临时注入 `CPA_API_KEY`，保留 Host 的启动环境；SDK 子进程仍清空继承环境、禁 proxy/telemetry/tracing。没有放宽 SDK/Reader/正式 Graph，不运行冻结 R01/R05 四槽 A/B，不接触真实 Kubernetes、Repair/HITL/Memory/Checkpoint 或稳定部署。

## 本轮真实证据

日期：2026-10-20，macOS arm64 / CPython 3.13.14。真实运行源码 Head：`b1fc414fc967178a257aa464d1724eb9aa729a99`；工作树在运行时干净，使用仓库锁定环境，没有下载或升级。下表是私有合成轨迹的白名单元数据摘要，不含响应正文、Authorization、Key 或私有原始请求。

| Probe | HTTP / 模型回显 | finish_reason | 原始输入/输出/总 Tokens | reasoning / cached | SDK 对比 | HTTP 延迟 |
| --- | --- | --- | --- | --- | --- | --- |
| L1 合成中文文本 | 200 / gpt-6-luna | stop | 321 / 44 / 365 | 30 / 0 | MATCH | 5001 ms |
| L2 合成 pods_get | 200 / gpt-6-luna | tool_calls | 423 / 34 / 457 | 0 / 0 | MATCH | 2202 ms |
| L3 配对 ToolMessage 续答 | 200 / gpt-6-luna | stop | 437 / 54 / 491 | 0 / 0 | MATCH | 2852 ms |

本 Worker 本轮及累计可观察的真实模型 HTTP 尝试均为 **3**；此前失败启动未发模型 HTTP。三个响应报告合计输入 **1181**、输出 **132**、总 **1313** Tokens，其中报告 reasoning **30**、cache **0**；reasoning 已包含在输出字段，不能再加进总数。客户端 HTTP 延迟合计 **10055 ms**，不代表完整任务墙钟或 CPA 上游独立处理时长。用户另述的其他 Codex 连通性测试不在本 Worker 的计数/账单可观察范围内。

L2 仅返回一个 `pods_get`，执行层检查参数为 `namespace=kube-triage-demo`、`name=p1a-synthetic-pod`；没有执行真实 Reader。Tool ID 非空合法，私有记录保留其 SHA256：`b40ef3bcfea8199bb7477ce42688ba19120b9b091ba1d9d5c7b0853e67be3422`。L3 请求体按该 ID 配对 ToolMessage，固定假 UID `p1a-fake-uid`，回执为 Unknown/纯合成无真实读取；wire guard 校验实际发送消息。最终自然语言语义未人工审阅，不能从字符串黑名单或协议成功推导语义 PASS。

私有目录 0700、文件 0600 已核对；原始回复和行级证据不进 stdout、PR 或云 Trace。可核对摘要：

- 私有 `summary.json` SHA256：`6226e9314c621a939ce83eb657ab0566d560adb0447a491e34cde72f86b7707a`。
- 私有父进程 `launch.json` SHA256：`14374bcdd85fa692851c850e05c6a741c2f389ba1edd35de60acaedeb1050680`。
- 父进程记录 `phase=child_exit`、`exit_code=0`、`client_http_attempts=3`、`protocol_status=PASS`；`status=UNKNOWN`、`semantic_status=UNKNOWN`、`semantic_review=NOT RUN` 刻意保持，不是协议失败。

没有追加可选 L4，没有自动重跑或增加请求来追求更好输出。实际价格、失败计费、CPA 内部路由/重试/隐藏账单及真实底层模型版本依然 UNKNOWN；原始 Usage 是 CPA 声明值，SDK 一致不等于独立账单核验。

## 实现、安全出口与回归

独立 CLI 固定三步人工合成序列，Schema 复用现有构造器，`validate_call` 后再限制到精确假 Pod。P0 Mock-only、`live_gate=BLOCKED`、旧 dry-run/readiness、正式源码与冻结数据均不改。

冻结版本 `openai==3.29.0`、`langchain-openai==1.7.0`、`httpx==0.28.1`、`httpcore==1.0.9`、`anyio==4.15.1`。显式 Chat Completions / `use_responses_api=False`、`max_retries=0`、非流式、输出上限1024；HTTP retries=0、trust_env=False、无 redirect。每次 HTTP 前预约，最多24次/600秒（含预连接）/单次45秒/串行，异常 STOP，无重连或自动补跑；这不是费用硬上限。

父进程只预连接批准的数字 IP/端口，此时不发送 HTTP/Key；通过 `pass_fds` 交给 macOS `(deny network*)` 子进程，无网络 allow 规则。冻结 httpcore/anyio backend 核对 socket 实际 peer，只消费一次连接，三步复用 keep-alive；第二地址、重连、Unix socket 均拒绝。合成 OS 测试已证实继承连接可读写，而新建到相同服务或另一端口的连接均 EPERM。没有用 Python monkeypatch 冒充 OS 隔离，没有启动隧道、服务、Compose 或容器。

私有父日志目录在 TCP 前建立，结束时独占写 `launch.json`；子进程先写 entered 标记再允许 HTTP。TCP/子进程非零/启动异常/超时均有脱敏父回退审计：标记前0 HTTP，标记后计数不完整为 UNKNOWN，完整报告保留实际计数。子进程 stdout/stderr 被捕获、不重放任意 bootstrap 错误；公开输出仅白名单状态，不含私有回复。

验证：本机最终全量 `648 passed in 56.43s`（含63项专项），Ruff、`git diff --check`、3个 Pod manifest 检查 PASS；源码 Head 的 CI Python `645 passed, 3 skipped`（macOS专属实例在Linux跳过，本机覆盖）、Web/Compose PASS，独立 Reviewer approved。最终文档提交的 CI/复审见 PR 正文；纯文档更新不伪称重新做了模型调用或本机全量测试。

负测覆盖400/403/422/429/5xx、redirect、断连/超时、坏JSON、模型回显不符/Key回显脱敏、Usage缺失、finish_reason、工具ID/参数、未知工具/跨Namespace/其他Pod、无证据同义结论、24次/600秒/并发、其他地址/路径、默认零出站、精确LAN例外、peer/重连/Unix socket、OS禁新连接、stdout私有证据及完整父启动审计。旧CLI曾在OS全禁网验证：dry-run24槽，readiness/P0各4离线槽/12模拟HTTP；不是实际A/B。

## 历史失败与当前 Gate

此前源码 `821eb33192a4a3160a4da24305af15ea5b0484cb` 启动一次，在协议子进程目录创建前 STOP，模型HTTP0，具体异常未保存，保持 UNKNOWN；不能把首次失败归因于服务或模型。本轮经用户新确认后用已审阅源码启动的新运行成功，不覆盖该历史失败。macOS任意数字IP Seatbelt过滤原型曾FAIL，默认Docker及OrbStack context不可连接；最终采用继承固定连接的OS全禁网机制，未改为通配端口规则。

| Gate | 状态 | 证据/边界 |
| --- | --- | --- |
| #58 / main / Worktree / 仅P1-A | PASS | 实时基线、冻结源码、独立CLI |
| 私有配置 / 指定HTTP例外 / 宿主机直连 | PASS | 用户明确授权，本轮真实3次HTTP200 |
| TLS（精确HTTP例外） | NOT RUN | 不伪称TLS PASS，不放宽其他地址 |
| L0离线边界 / L5负测 / OS出口 | PASS | 原代码/冻结文件无差异、63专项、本机648全量 |
| L1文本 / L2 tools / L3 ToolMessage | PASS（有限合成wire） | 3次200、模型回显一致、ID配对、Usage MATCH |
| 最终自然语言语义 / 独立账单 / CPA内部行为 | UNKNOWN | 人审NOT RUN；客户端不可独立观察上游 |
| 首次启动 / Seatbelt远端IP原型 | FAIL（历史） | 本轮成功不抹除历史失败 |
| L4可选负测 / B8 / P1-B / P2 / 真实K8s / 真人盲审 | NOT RUN | 不产生下一阶段GO，不追加模型请求 |
| 最终交付CI / 独立Reviewer | 见PR正文 | 针对最终Head记录，不沿用过时批准 |

回退为退出CLI或回滚PR；无部署、数据库、Memory/Repair/Checkpoint迁移。Issue #41保持Open，PR保持Draft，不自动合并；P1-B/P2、B2/B3及历史FAIL边界保持。
