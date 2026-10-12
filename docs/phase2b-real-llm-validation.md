# Phase 2B：Real LLM 独立验收记录（2026-10-12）

**结论：B01–B08 全部 PASS，可以进入 Phase 3 的学习与设计。** `deepseek-flash` 实际返回标准 Tool Calls，经 Mock MCP 和项目专属 Real Kubernetes MCP 读取，再依据真实证据形成中文诊断。本轮没有实现自动修复，也没有修改集群资源。B09 已记录实测用量；供应商/代理未提供可靠费用信息，因此不猜测金额。

状态定义：`PASS` 为本轮实际验证；`FAIL` 为实际运行但未满足判据；`NOT RUN` 为未执行；`BLOCKED` 为前置条件阻断。历史 Fake Model 和固定命令结果不充当真实模型证据。

## 基线与真实代码连接

`git fetch origin` 后从 `origin/main=09c9ca322142d0629392798eefd334614b73fa6b` 建立 `codex/phase2b-real-llm-validation`，没有复制旧工作树的改动。`server/aegra.json` 注册 `graph_id=agent`，指向 `graph.py:graph`。`graph.py:_route` 在 `llm.enabled()` 为真时进入 `_llm`；`llm.py:chat_model()` 用 `LLM_MODEL`、`LLM_API_KEY` 和可选 `LLM_BASE_URL` 创建 `ChatOpenAI`。`_llm` 从 `mcp_client.py:_allowed_tools` 发现且核对四个原生工具，通过 `bind_tools` 向模型声明，并发送 `prompts.py:SYSTEM_PROMPT` 和 Thread 中的消息。模型若返回 `AIMessage.tool_calls`，`_after_llm` 转到 `_execute_tool`；后者经 `call_tool` / `validate_call` 做白名单、Namespace、参数和预算检查，调用 MCP，并为每个调用写入同 ID 的 `ToolMessage.tool_call_id`。`_after_tools` 在 LLM 模式回到 `_llm`，直到模型给出最终中文回答或达到上限。Aegra 的 Run 通过 SSE 发送 `data:`，Thread State/History 从 Checkpoint 读取消息。`scripts/acceptance.py` 用 `LLM_ENABLED=false` 走 `parse_demo_command`，只验证固定命令路径。

## 验收表

| ID | 验收项 | 状态 | 真实证据（脱敏） |
| --- | --- | --- | --- |
| B01 | 独立 Compose、凭据隔离和其它项目未受影响 | PASS | 独立工作树及 `-p kube-triage-phase2b-demo`；端口 12027/13001；独立容器、网络和卷。临时 `.env`、项目受限 kubeconfig 为 Git 忽略的 0600 副本，`.local` 为 0700；结束已删除。稳定项目 6 个及 `ragflow-lab` 5 个容器 ID 前后一致。 |
| B02 | 真实模型生成标准 Tool Calls | PASS | 隔离 API 容器实际 `LLM_ENABLED=true`、模型 `deepseek-flash`。容器内真实模型探测返回 `pods_list_in_namespace(namespace=kube-triage-demo)`，调用 ID 存在、`invalid_tool_calls=0`，用量 710 输入/58 输出 Token。 |
| B03 | Real LLM + Mock MCP 工具调用、ToolMessage 配对 | PASS | B1：模型调用 Pod 列表及两次 `pods_get`，3 个 ID 全配对；B2：模型调用 Pod 列表、Event、Pod 详情、Log，4 个 ID 全配对。ToolMessage 均成功且带 `mock=true`/`static-fixture`。 |
| B04 | 模型基于工具结果形成中文证据诊断 | PASS | B2 引用 CrashLoopBackOff、Back-off Event 和 `database unavailable` 样例日志，分列现象/证据/原因判断/未确认项，并说明 Mock 必须在真实集群复核。日志文本不足以证实容器真实退出码，其对退出链路的部分措辞偏强，不能作为真实根因定论。 |
| B05 | Real LLM + Real MCP/Kubernetes 实际读取 | PASS | Real MCP `tools/list` 恰好四个原生只读工具，四工具直接调用成功；成功的 Real 浏览器 Run 调用 Pod 列表、Event、Log，ToolMessage 均成功且无 Mock 标记。`triage-sample` 为 `Succeeded`、`Completed`、`exitCode=0`、`restartCount=0`；Event 当前无记录；日志显示正常开始与完成。 |
| B06 | 浏览器展示 Tool Call、结果、最终回答；SSE/History | PASS | 独立 Web 显示 API `localhost:12027` 与 `graph_id=agent`。Mock 和 Real 浏览器 Thread 都显示 Tool Call、同 ID Tool Result、中文最终回答；成功 Real Thread `141cfc77-1a70-41c6-a8e1-ed50741e57d6` 的 Run 为 `success`、State `next=[]`、History 7 项。B1/B2 的 Agent Protocol SSE 逐行观察到 `data:`，含 `messages/updates/values/end`。 |
| B07 | Namespace/只读/RBAC、越权拒绝 | PASS | Real API 中 `validate_call` 拒绝 `kube-system`、`pods_delete` 与未知字段，均为 `policy`；B3 模型也自行拒绝且未发工具调用。Real MCP `read_only=true`、仅四工具；受限身份对本 Namespace 的 Pod/Event/Log 为 `yes`，对 `default`、`kube-system`、Secret、Pod create/delete 为 `no`。 |
| B08 | pytest/Ruff、旧 Mock/审批/Checkpoint 基本回归 | PASS | 修复后 `uv run --python 3.13 --frozen --offline pytest -q`：38 passed；Ruff 全 PASS；Mock/Real Compose `config --quiet` PASS。独立 API 暂切 `LLM_ENABLED=false` 后重跑旧验收，Auth、Mock MCP、越权拒绝、SSE、审批、重启和 History 全 PASS；再恢复 `LLM_ENABLED=true`/Real URL。 |
| B09 | 模型轮次、工具次数、耗时、Token/成本（若可得） | PASS | B1：3 次模型决策/3 次工具，8.69 秒，2789 输入/1182 输出 Token；B2：3/4，11.43 秒，3115/1685 Token；成功 Real Run：3/3，约 9.97 秒，7442/1177 Token。费用没有可靠价格映射，不作估算。 |

## Gate A/B：真实模型与 Mock MCP

原有 `.env` 仅屏蔽读取：`LLM_ENABLED=true`、模型 `deepseek-flash`、Key/URL 已设置；URL 为 HTTPS 且不是回环地址。没有打印 Key、URL 全文、Demo Token、容器 Env 全量或未经脱敏的日志。`infra/compose.yaml:api.environment` 注入四个 LLM 变量，隔离 API 内布尔检查证实生效；Web 构建使用 `NEXT_PUBLIC_API_URL=http://localhost:12027`，浏览器确实连接该独立 API。Compose 只用 `config --quiet`。

首次外部模型探测被自动审批审查拒绝，因为 System Prompt、工具 Schema 和测试问题会发送到外部端点。用户随后明确批准本项目当前模型端点接收这些内容和脱敏 Mock/项目专属 Kubernetes 结果。本轮只在授权后继续真实请求；直接探测得到结构化 Tool Call，而非普通文字。

B1 Thread `ca357572-2aa8-4392-869b-3e19162d0165`：模型先列 Pod，再查两个 Pod；SSE 有 `data:`、History 7 项；最终指出 `healthy-pod=Running` 与 `crashloop-pod=CrashLoopBackOff` **仅是 Mock 静态数据**。B2 Thread `b4ae707f-8c94-438a-9607-2eb2548409da`：模型先并行列 Pod/查 Event，再查 Pod/Log；四次工具结果均配对。B3 Thread `0b8e841f-cb01-47b8-b8f6-2c0fc20fb039`：模型直接拒绝跨 Namespace 与删除，未发工具调用。独立 Web 的 Mock Thread `2b64836e-6c72-4ea9-8307-6b415ad338c3` 也亲见模型 Tool Call、结果和中文回答，并明确标注 `mock=true/static-fixture`。

## Gate C：真实 Kubernetes 与最小修复

只读 SSH 核对 `k8s-m` 上的 `kube-triage-demo` Namespace、`kube-triage-reader` ServiceAccount/Role/RoleBinding 及 `triage-sample` 均带本项目标签。现有受限 kubeconfig 仍有效，本轮只复制到 0700/0600 的忽略路径；未复制管理员 kubeconfig、关闭 TLS 验证或刷新 Token。受限身份直接读取 `triage-sample=Succeeded`，RBAC `can-i` 矩阵符合 B07。未创建、修改或删除任何集群对象。

隔离 Real MCP 通过 `--profile real` 启动，API 以 `MCP_SERVER_URL=http://k8s-mcp:8080/mcp` 强制重建以刷新进程内工具缓存。`tools/list` 恰好四工具，四工具直接调用均成功且无 Mock 标记；`events_list` 本轮为 `# No events found`，不能用历史 Event 冒充当前证据。

**发现 → 原因 → 修复 → 复测：** 首次 Real 浏览器 Thread `a0c7aa2f-084d-44ae-84d6-dd905aefd7a9` 中，模型先按原生 Schema 调用 `pods_log(namespace,name,container=sample)` 并省略 `tail`，再调用 `pods_log(namespace,name,container=sample,tail=100)`。旧 `validate_call` 分别因缺少 `tail`、多出 `container` 返回 policy 错误；第三次不带 `container` 才读到日志，但模型已用完 4 次决策，最终只有预算提示。实际 Real MCP Schema 仅强制 `name`，`container` 和 `tail` 可选。本项目仍强制固定 Namespace，并选择更小的 `tail=20` 安全默认。

修复只改现有 `mcp_client.py:validate_call,call_tool`：省略 `tail` 时补 20、继续限制 1–100；允许经过 Kubernetes 名称格式校验的原生可选 `container`，继续拒绝未知字段、跨 Namespace 和写工具。没有新增 Adapter、DTO、第二套工具 Schema 或修改 System Prompt。新增单测覆盖默认值、`container` 和未知字段拒绝；38 项测试/Ruff、旧 Mock/审批/Checkpoint 回归通过。重建后的隔离 API 直接以 `container=sample`、缺省 `tail` 从 Real MCP 成功读到日志。

## 最小真实 Agent Trace（Real 来源）

成功的浏览器 Thread `141cfc77-1a70-41c6-a8e1-ed50741e57d6`，Run `success`、State `next=[]`、History 7 项。下列 ID 来自真实模型响应与 Aegra State，非手工拼装：

1. **User：**“请检查 `kube-triage-demo` 的 Pod，并调查 `triage-sample` 的 Pod 状态、相关 Event 和日志。若没有故障证据请明确说明。”
2. **模型决策 1：**并行调用 `pods_list_in_namespace(namespace=kube-triage-demo)`，ID `call_00_2GFwH1aQmgEmbfoSixwO5374`；`events_list(namespace=kube-triage-demo)`，ID `call_01_tPpv6jPUzmuxJyRE7CLt2949`。
3. **Real ToolMessage：**同 ID 一一配对且均为 `success`；Pod 是 `triage-sample`，`Succeeded`、`Completed`、`exitCode=0`、`restartCount=0`；Event 返回 `# No events found`。均无 `mock=true`。
4. **模型决策 2：**调用 `pods_log(namespace=kube-triage-demo,name=triage-sample,container=sample)`，ID `call_00_zNLxtqHKzyujM9VUOoBV8642`，省略 `tail`，执行层补 20；同 ID Real ToolMessage `success`，日志为 `triage sample: started`、`triage sample: complete`。
5. **模型决策 3 / 最终报告：**中文结论为“未发现任何故障证据”，说明这是 `restartPolicy: Never` 的正常完成 Pod；Event 为空可能受保留时间影响。没有编造 CrashLoopBackOff 或数据库故障，也没有执行修复。

## 用量、限制与清理

成功 Real Run 的三次模型响应合计 7442 输入/1177 输出/8619 总 Token，三次工具调用，Run 时间戳差约 9.97 秒。首次失败的 Real Run 也如实记录：4 次模型决策、5 次工具调用（2 次 policy 拒绝）、10685 输入/492 输出 Token，最终只有预算提示；成功复测不抹去这次失败。供应商没有返回费用金额；`deepseek-flash` 可能经兼容代理计价，不能凭模型名推断成本。

本轮核心端到端请求为 Mock B1/B2/B3、Mock 浏览器、Real 浏览器首次及必要的修复复测，共 6 次；另有 1 次受控 Tool Calling 探测。多出的一次 Real 请求仅用于实测 Bug 的必要复验。

结束时只对 `kube-triage-phase2b-demo` 执行 `docker compose ... --profile real down`，核对两个卷的项目标签后精确删除它们，并删除忽略的临时 `.env`、受限 kubeconfig 和测试脚本。`docker compose ls` 最终仅剩稳定 `kube-triage-agent` 与 `ragflow-lab`；两项目所有容器 ID 前后一致。没有全局 prune、没有触碰其它项目数据或集群资源。PR 保持 Draft，不合并、不关闭 Issue。
