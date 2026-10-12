# Phase 3A：真实模型 + Mock MCP 诊断评测报告（2026-10-12）

**实现 Gate：PASS。执行 Gate：PASS，含质量问题。** 这是 `deepseek-flash` 经真实 Aegra Agent Protocol 的 12 次模型 Run，不是 FakeModel、固定命令或真实 Kubernetes。原始合成证据、完整回答、人工逐条评分保存在本机 Git 忽略的 `.local/eval-runs/phase3a-baseline`（目录 0700、文件 0600）；此文档只包含脱敏摘要。基线执行时 `HEAD=08a94b2bf12a9b738634995870c543f3900a4047` 且 Worktree 含本 PR 未提交变更，故该 SHA 单独**不代表**最终代码版本；PR commit 会固定实现文件。Golden 与 System Prompt 在同一 12 次基线期间没有修改。

## 隔离与执行

只读 Docker 预检记录稳定项目 `kube-triage-agent` 六个容器 ID：`0071c534ba8f`、`86f20eff96de`、`f39cb62b7bdf`、`0448756ba411`、`eac83ce1df53`、`06d49306e2c3`；`ragflow-lab` 五个：`ec91a583a0c0`、`9fa3d95bac3a`、`7c09066f7eb6`、`8d31201680ff`、`f119a6b94aa5`。12028 端口空闲。独立项目名 `kube-triage-phase3a-eval`，只启动 PostgreSQL、Redis、API、Mock MCP；API 绑定 `127.0.0.1:12028`，未启动 Web/Real MCP。已有稳定 `.env` 仅按白名单私有读取模型名、Key、HTTPS URL；配置文件位于忽略的 `.local`，未打印值。容器内只以布尔值核对 `LLM_ENABLED=true`、Key 存在与 Mock URL；直接 `tools/list` 恰好四个原生工具。

先跑独立 Smoke：Aegra `success`，4 个标准 Tool Calls 与 ToolMessage 全配对，Mock 返回目标 Pod 证据；这条 Smoke 不计入下面 12 次。随后用 `python3 scripts/eval_phase3a.py --cases eval/cases.json --repeats 3 --out .local/eval-runs/phase3a-baseline --env-file .local/phase3a.env` 串行执行。每次新 Thread，SSE 到 `end`，State 无待执行节点，History 为 7 或 9 项，Run API 状态均为 `success`。模型用量来自 AIMessage 元数据，费用未知。

## 12 条逐项结果

列中 `P/E/S` 表示 Tool Call ↔ ToolMessage 协议、目标关键证据、工具选择合规；`诊断/落地` 为人工 `diagnosis_correct(0/1)` 与 `grounding_score(0–2)`。每条 Run 状态由 Aegra + SSE/State 检查，人工分数引用该 Run 的 ToolMessage，未以关键词自动给分。

| Case | Run | Aegra/Runner | 调用/决策 | P/E/S | 诊断/落地 | 秒 | Token 总数 | 人工复核重点 |
| --- | ---: | --- | ---: | --- | --- | ---: | ---: | --- |
| crashloop | 1 | success/PASS | 6/4 | ✓/✓/✓ | 1/1 | 12.905 | 8676 | 多查 `oom-pod` 用满工具预算；把数据库日志推成“直接原因”偏强 |
| crashloop | 2 | success/PASS | 4/3 | ✓/✓/✓ | 1/1 | 10.524 | 5726 | “数据库不可达导致退出”仍未获数据库侧证据 |
| crashloop | 3 | success/PASS | 4/3 | ✓/✓/✓ | 1/2 | 11.323 | 6109 | 明确日志不等于数据库已宕 |
| imagepull | 1 | success/PASS | 4/3 | ✓/✓/✓ | 1/2 | 8.462 | 5598 | 没有编造容器日志或 DNS/认证根因 |
| imagepull | 2 | success/PASS | 4/3 | ✓/✓/✓ | 1/2 | 7.747 | 5156 | 明确只知镜像拉取失败，子原因未明 |
| imagepull | 3 | success/PASS | 4/3 | ✓/✓/✓ | 1/2 | 12.791 | 6334 | 正确区分其它 Pod 的 BackOff Event |
| oomkilled | 1 | success/PASS | 4/3 | ✓/✓/✓ | 1/1 | 10.658 | 5700 | 最近一次 OOM 证实；“反复被杀”与批处理因果偏强 |
| oomkilled | 2 | success/PASS | 4/3 | ✓/✓/✓ | 1/1 | 11.068 | 5769 | BackOff 与 OOM 的因果时间线未给出 |
| oomkilled | 3 | success/PASS | 4/3 | ✓/✓/✓ | 1/1 | 10.295 | 将短日志形容为中断式终止证据偏强 |
| healthy | 1 | success/PASS | 4/3 | ✓/✓/✓ | 1/1 | 9.313 | 5742 | “当前健康”比“暂无故障证据”略强；无误报 |
| healthy | 2 | success/PASS | 4/3 | ✓/✓/✓ | 1/2 | 8.585 | 5836 | 限定结论仅适用于静态样例；无误报 |
| healthy | 3 | success/PASS | 4/3 | ✓/✓/✓ | 1/2 | 9.400 | 5544 | 没把其它 Pod 的 Warning 归给目标；无误报 |

**总分母始终是 12：** 完成率 12/12；协议通过率 12/12；工具选择合规率 12/12；关键证据取得率 12/12；工具实际成功 50/50；人工分类正确 12/12；平均 grounding 1.50/2；健康误报率 0/3。运行失败 0、BLOCKED 0、PENDING 0。总模型决策 37 次，工具调用 50 次。墙钟耗时中位 10.410 秒、最大 12.905 秒。12 条均返回 Token Usage，总计输入 52,952、输出 18,861、合计 71,813；不估算费用。

## 一条真实证据链（imagepull 第 2 次）

本次独立 Thread 从中性问题“调查 `imagepull-pod` 是否异常”开始。模型先发 `pods_list_in_namespace(namespace=kube-triage-demo)`（ID `call_00_ET_QfuQBNlenTzE7AMI3HMX4034`）和 `events_list(namespace=kube-triage-demo)`（ID `call_01_ET_f8iqdWOmcyP6gOuvh8cZ7324`）；两条 ToolMessage 同 ID 成功。列表中目标 phase=`Pending`；Namespace 事件中只有 `involvedObject.name=imagepull-pod` 的 `Warning/Failed` 与目标相关，另两个 BackOff 属于其它 Pod。接着模型发 `pods_get(name=imagepull-pod)`（ID `call_00_OAWEZfvbvUJ30yF5vwHm0357`）和 `pods_log(name=imagepull-pod)`（ID `call_01_h2jMoXVtffqDwRmFx3R77164`）；同 ID ToolMessage 分别给出容器 `waiting.reason=ImagePullBackOff, ready=false, restartCount=0` 与 `available=false, logs=null, reason=container has not started`。最终中文报告判断镜像拉取阶段异常，明确未能区分认证、DNS、仓库不存在等子原因，没有编造运行日志。Aegra Run=`success`、State `next=[]`，本次 3 次模型决策、4 次工具，7.747 秒、5,156 Token。上述 ID 均来自实际 State，而非手工生成。

## 失败与边界

模型 Run 本次没有失败，但“工具全成功”并非“推理全可靠”。CrashLoop 第 1 次还查看了无关 `oom-pod`，占满 6 次工具额度；它在第 4 次模型决策完成最终回答，**没有**触发预算终止。若预算终止，Runner 会标为非正常结束，不能计成功。OOM 三次都依据 `lastState.terminated.reason=OOMKilled` 正确分类，却有“反复 OOM”或“批处理导致内存超限”的越界说法；只有最近一次终止原因和重启次数，缺内存指标与完整时间线。健康样本三次没有把其它 Pod 的 Warning Event 错归目标，但其中一次用了过强的“当前健康”。这些 grounding 扣分已写入人工复核记录，不能用 100% 分类率掩盖。

旧固定命令回归首次 FAIL 一项：脚本错误地要求 Pod 列表字符串含 `CrashLoopBackOff`，与本轮正确的 `phase=Running` 不符。仅调整测试断言，让列表检查 Pod 存在、详情再检查容器 Waiting；独立项目复跑后 22 项均 PASS。没有改 Golden、System Prompt 或 Graph 来迎合结果。

四类各三次只覆盖固定合成证据，不能宣称真实生产准确率。Mock 缺时间戳、资源限制、节点/镜像细节和真实日志噪声；人工评分有主观性。下一步应先收紧因果表述与健康措辞的提示词假设，在不改本组 Golden 的前提下增加独立盲样，再谈 Phase 3B 的更广覆盖。Phase 2B 的真实正常 Pod 证据仅作历史参照，本轮没有访问或修改真实 Kubernetes。

## 回归与清理

最终 `uv run --python 3.13 --frozen --offline pytest -q`：44 passed；Ruff 对 `src tests` 和两个脚本通过。`pnpm lint` 返回 0（仓库原有 18 条 warning），`pnpm build` 返回 0；`docker compose ... config --quiet` 通过。独立项目在 `LLM_ENABLED=false` 下复跑固定命令、鉴权、SSE、审批 interrupt/resume、重启与 Checkpoint/History，共 22 项 PASS。

删除前核对四容器及两个具名卷均有 `com.docker.compose.project=kube-triage-phase3a-eval`。随后仅对该项目执行 `down`，精确删除这两个卷和 `.local/phase3a.env`、`.local/phase3a-fake.env`。清理后仅剩原有 `kube-triage-agent` 六容器与 `ragflow-lab` 五容器，ID 与预检完全相同；Phase 3A 容器、网络、卷均不存在。私有评测证据保留在 Git 忽略目录供本机复核。没有运行集群写命令、应用 YAML、刷新 kubeconfig 或查询真实 Kubernetes。
