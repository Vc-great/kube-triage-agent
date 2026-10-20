# Issue #41 P1-A CPA / gpt-6-luna Provider Contract Gate

对应 [P1-A 方案](plans/issue-41-p1a-cpa-gpt6-luna-provider-contract.md)，Planning PR [#58](https://github.com/Vc-great/kube-triage-agent/pull/58) 已合并。实施及本轮重新 fetch 的 `origin/main=371715551911f713df3ec2d6dce62eed51fcf6f4`；独立 Worktree `provider-contract-3`，分支 `ao/provider-contract-3/p1a`。最终交付 Head、CI、独立 Reviewer 以 [Draft PR #59](https://github.com/Vc-great/kube-triage-agent/pull/59) 正文为准。

**当前结果：已尝试启动一次真实 P1-A，但在协议子进程启动前失败；模型 HTTP 请求为 0，L1–L3 BLOCKED。不能判断 CPA 协议或 gpt-6-luna 能力，不能产生 P1-B GO。**

## 本轮明确授权与范围

用户在初始任务后进一步明确：允许从现有 `.env` 使用 CPA endpoint/key；随后明确指定 `http://192.168.31.110:8317/v1` 为本轮测试地址。该指令优先于规划中“远端必须 HTTPS”的通用条件，构成**仅此 IP、8317 端口、`/v1/chat/completions` 路由的明文 HTTP 例外**。不推广到其他内网地址、路径、端口或任意 HTTP。

本机进程只在内存解析用户授权 `.env` 的所需配置，确认 endpoint/key 存在、模型匹配；没有输出、复制、上传文件内容或 Key，也不修改 `.env`。仓库 CLI 不加载 dotenv；一次性执行加载器将 Key 传入私有环境。上游链路、代理内部重试和账单不可观察，保持 UNKNOWN。P1-B/P2、真实 Kubernetes、Repair、正式 Graph/HITL/Memory 和稳定部署均未授权、未运行。

## 实现与出口隔离

独立 `scripts/issue41_p1a_probe.py` 固定三步人工合成序列：中文文本 → `pods_get(kube-triage-demo/p1a-synthetic-pod)` → 配对 ToolMessage（`p1a-fake-uid`）。不加载冻结 R01/R05，不运行 A/B，不执行 Reader。Schema 复用现有构造器；`validate_call` 后再限制为精确假 Pod。P0 Mock-only、`live_gate=BLOCKED`、旧 dry-run/readiness 及正式源码不改。

锁定 `openai==3.29.0`、`langchain-openai==1.7.0`、`httpx==0.28.1`，继承连接适配额外核对冻结 `httpcore==1.0.9`、`anyio==4.15.1`；没有升级依赖。显式 Chat Completions、`use_responses_api=False`、`max_retries=0`、非流式、输出 1024；HTTP retries=0、trust_env=False、无 redirect。每个 HTTP 尝试前预约，最多 24 次、总 600 秒（含预连接）、单次 45 秒、串行；异常 STOP，不重连、不补跑、不自动切换协议或参数。计数不是费用上限。

macOS Seatbelt 不支持任意数字远端 IP 的过滤规则（原型已 FAIL）；默认 Docker 与已有 OrbStack context 均不可连接，未启动/改变其服务。最终采用更小的受限机制：

1. 父进程只向批准的数字 IP/明确端口预建立一条 TCP 连接，此时不发送 HTTP 或 Key。
2. 通过 `pass_fds` 将该连接交给 `sandbox-exec` 的 `(deny network*)` 子进程，无网络 allow 规则。子进程无法新建 TCP、DNS、UDP 或额外出口。
3. 冻结 httpcore/anyio 适配器检查 socket 的实际 peer，再把已有 socket 包装成 SDK transport。只允许消费一次连接；后续三步复用 keep-alive。CPA 关闭连接、另一地址/端口、Unix socket 或重连均 STOP。没有用 Python monkeypatch 冒充 OS 隔离。
4. 子进程清空继承环境，仅保留必要配置；禁 proxy/telemetry/SDK tracing。HTTP body 与固定合成消息逐字典比较，拒绝其他模型、路径、正文或工具。

已用本任务临时合成 HTTP/1.1 服务实测：三步可在 OS 全禁网下复用连接，继承连接可读写；新建到相同服务或另一端口的连接均 EPERM。此机制不改变 CPA 服务、不创建隧道、不启动 Compose 或任何稳定环境。

私有输出复用 `PrivateOutput`：新建目录 0700、文件 0600，无覆盖/符号链接。stdout 仅含状态/计数，私有回复与行级证据不进入任务日志。记录脱敏模型回显、HTTP 状态、finish_reason、ID/请求摘要、原始/SDK Usage、延迟；400/422 仅记录错误结构，不输出异常内容。协议通过与语义分开：`protocol_status` 可 PASS，整体/语义仍 UNKNOWN、人审 NOT RUN；固定短语不能证明语义正确。缺失 Usage、实际费用和 CPA 隐藏行为不填 0。

## 真实尝试与证据边界

2026-10-20，以源码 Head `821eb33192a4a3160a4da24305af15ea5b0484cb`、已批准地址与私有 Key 启动**一次**，没有补跑。加载器返回 `STOP / launch_or_timeout`；协议子进程的私有目录及 `summary.json` 均不存在。按源码调用顺序，HTTP 只可能在子进程创建私有目录之后发生，因此本次没有 HTTP/模型请求，没有任何 CPA HTTP 状态、Usage、模型回显或 Tool ID 回执。

该版本的父进程异常包装未保留具体异常类别，因此**不能判定**是连接拒绝、超时、Host 防火墙还是其他启动原因；精确类别记 UNKNOWN，不把它写成模型失败。随后只读 Host 路由检查显示目标经 `en0`，这不能证明端口可达，未再发送 TCP/HTTP 探针。已补父进程 TCP 失败的私有审计（异常类型、数字 errno、0 HTTP，不含异常消息）及合成回归；没有为验证修复重跑真实 CPA。

原始私有模型轨迹没有产生；本报告不附任何 Secret、`.env`、私有原始请求/响应或真实集群数据。未来若恢复，应由用户确认新的执行窗口/运行标识；不能以本次剩余计数自动补跑。

## 工程验证

环境：macOS arm64、CPython 3.13.14；复用 Host Runtime 与 uv 离线缓存，`uv sync --frozen --offline --python 3.13`，没有依赖下载/升级。

- PASS：在 `server/` 按当前 CI 文件集执行 `.venv/bin/ruff check ... ../scripts/issue41_p1a_probe.py`；`git diff --check`。
- PASS：`.venv/bin/python ../scripts/check_issue11_manifests.py`，3 个 Pod manifest。
- PASS：新增继承连接路径时全量 pytest `636 passed in 56.37s`；真实启动前最终专项 `54 passed in 3.78s`。补启动失败审计后最终全量 `640 passed in 57.26s`（含55项专项）；最终 CI/独立 Reviewer 以 PR 正文补充。
- 负测覆盖：400/403/422/429/5xx、redirect、断连/超时、坏 JSON、回显模型不符/Key 回显脱敏、Usage 缺失、finish_reason、工具 ID/参数、未知工具/跨 Namespace/其他 Pod、无证据同义结论、24 次/600 秒/并发、另一地址/路径、默认零出站、精确 LAN 例外、socket peer/重连/Unix socket、OS 继承连接与全部新连接拒绝、成功/失败 stdout 不泄漏。
- 旧 CLI 曾在 macOS OS 全禁网下验证：dry-run 24 槽；readiness/P0 各 4 离线槽、12 次模拟 HTTP，P0 live_gate=BLOCKED。旧脚本/冻结数据/生产源码与 main 无差异；不是实际 R01/R05 A/B。
- 初始 Head 的两项 Reviewer 必改已修复（stdout 私有证据、协议/语义分离），旧 Head CI/复审均通过。**新增继承连接路径的独立 Review 和最终 CI 另见 PR 正文，未返回前不沿用旧批准。**

## Gate

| Gate | 状态 | 证据与限制 |
| --- | --- | --- |
| #58 / 实时 main / 独立 Worktree / 阶段范围 | PASS | 实施及续作基线一致；仅 P1-A |
| endpoint / Key / 明文 HTTP 特例授权 | PASS | 用户明确指令；安全内存加载，无秘密输出；不代表 TLS 存在 |
| TLS（此次明确批准 HTTP） | NOT RUN | 此精确端点为明文例外，不伪称 TLS PASS；其他远端不放宽 |
| 原离线边界 / Mock / 合成 OS 隔离 | PASS | 冻结回归、预连接 peer、OS 禁新连接、54/55 项专项 |
| 远端 IP Seatbelt 原型 | FAIL | 平台不支持；最终未使用通配端口规则 |
| 实际启动 | FAIL | 一次启动 STOP，未进入协议子进程，异常类别 UNKNOWN |
| L1 文本 / L2 Tool Calling / L3 ToolMessage | BLOCKED | 模型 HTTP 0，无法判断 CPA 合约 |
| L4 可选真实合成负测 | NOT RUN | L1–L3 未成功，不追加 |
| CPA 状态/回显/Usage/延迟 | UNKNOWN | 没有 HTTP 响应，不填 0 或 Mock 值 |
| TCP 失败具体原因 / CPA 上游重试 / 实际版本 / 账单 | UNKNOWN | Host 路由不证明端口可达；未重试 |
| B8 / P1-B / P2 / 真实 K8s / 真人盲审 | NOT RUN | 没有 GO，不扩大授权 |
| 最终 CI / 独立 Reviewer | 见 PR 正文 | 针对最终 Head 重新获取结论 |

回退只需退出独立 CLI 或回滚 PR；没有服务、数据库、Memory/Repair/Checkpoint 或部署迁移。Issue #41 保持 Open，PR 保持 Draft，不自动合并，B2/B3 和历史 FAIL 保持。
