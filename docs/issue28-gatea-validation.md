# Issue #28 Gate A：离线验收记录

执行时间：2026-10-15 09:17（Asia/Shanghai）。基线为本次 `git fetch origin main` 后的 `45d9f7896f900d3c9fe8266aa29c81923b0dbd9f`，与提示词参考 SHA 相同。独立工作树 `/Users/vc/.codex/worktrees/issue28-gatea-context/kube-triage-agent`，分支 `codex/issue28-gatea-context`；用户主工作树的未跟踪文件未触碰。以下 PASS 只适用于所列离线层级。

层级：L0 为纯函数与静态检查；L1 为 Graph + FakeModel/工具 spy；L2 为 MemorySaver/模拟 Repair。真实 Provider、Aegra SSE/UI、真实 Kubernetes 均未执行。`server/tests/test_context_gate_a.py` 先于实现编写，首次运行因缺 `kube_triage.context` 采集失败；实现后新文件 23/23、全量 240/240 通过。

| ID | 状态 | 验收证据与范围 |
| --- | --- | --- |
| A00 | PASS | fetch 后 `origin/main` SHA 与参考相同；独立工作树/分支；复用已有 Python 3.14 依赖，无安装/下载，测试无真实服务。 |
| A01 | PASS | 关闭时短/长 Thread 的送模消息类型、顺序、正文、ID 及对象身份与旧路径一致；L1。 |
| A02 | PASS | 开启且未越阈值，0 轮省略、System 无警告；L0。 |
| A03 | PASS | 10/20/30 轮，等于阈值、差 1 估算单位、连续多轮省略；只删最旧完整轮；L0。 |
| A04 | PASS | 当前轮 3 个并发 Tool Call 与 success/error/budget 配对保留；原 4 决策/6 工具上限由既有回归继续通过；L0/L1。 |
| A05 | PASS | 缺最终 AI、孤儿/重复/跨轮复用 ID、旧 pending、未知类型、无 Human 一律不危险裁剪；L0。 |
| A06 | PASS | Prompt、完整 Reader Schema、结构化参数、ToolMessage 状态、2048 输出预留参与估算；非法配置与不可序列化值 fail closed；L0。 |
| A07 | PASS | 当前轮超限时模型/原生工具执行 spy 为 0，返回“诊断未完成”；Provider Context Limit 模拟异常被分类且不回显私有端点；L1。只读 tools/list 发现允许。 |
| A08 | PASS | 历史正常/当前 CrashLoop 与相反场景，当前消息和 ID 完整，`_has_tool_evidence` 只用当前轮；L0。没有真实模型语义诊断。 |
| A09 | PASS | 合成恶意 ToolResult、伪 `<system>`、虚拟 Secret 不进入 System 或审计；原 #13 离线执行边界回归通过；L0/L1。真实模型抗注入 NOT RUN。 |
| A10 | PASS | MemorySaver 中完整 State/Checkpoint 保留；`/repair-demo` 绕过 Context Manager；既有模拟 Repair Approve/Reject/Resume 测试通过，真实写 0；L2。历史 B06 未重演。 |
| A11 | PASS | Ruff、全量 pytest、Manifest、两套独立 Compose `config --quiet`、`git diff --check` 通过。远端 CI 在 Draft PR 创建前 NOT RUN。 |
| A12 | NOT RUN | 本文件、设计与面试文档已编写；Draft PR、独立 Review 与 CI 状态待创建后记录。 |

## 实际执行命令与分母

在独立工作树运行；`PYTHONPATH=server/src` 强制加载本分支代码，复用主 checkout 已有 Python 3.14 虚拟环境中的依赖。未执行包安装。

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=server/src /Users/vc/code/kube-triage-agent/server/.venv/bin/python -m pytest -p no:cacheprovider -q server/tests/test_context_gate_a.py
=> 23 passed / 23 collected
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=server/src /Users/vc/code/kube-triage-agent/server/.venv/bin/python -m pytest -p no:cacheprovider -q server/tests
=> 240 passed / 240 collected
RUFF_CACHE_DIR=/private/tmp/issue28-ruff /Users/vc/code/kube-triage-agent/server/.venv/bin/python -m ruff check server/src server/tests scripts/eval_issue12.py scripts/prepare_issue12_blind_review.py scripts/summarize_issue12_human_review.py scripts/eval_phase3a.py scripts/check_issue11_manifests.py
=> All checks passed
PYTHONDONTWRITEBYTECODE=1 /Users/vc/code/kube-triage-agent/server/.venv/bin/python scripts/check_issue11_manifests.py
=> PASS: 3 distinct Pod manifests
POSTGRES_USER=ci_user POSTGRES_DB=ci_db POSTGRES_PASSWORD=ci_placeholder DEMO_API_TOKEN=ci_placeholder LLM_MODEL=ci_placeholder LLM_API_KEY=ci_placeholder API_PORT=12128 WEB_PORT=13128 REPAIR_ENABLED=false docker compose -p kube-triage-issue28-gatea-real -f infra/compose.yaml config --quiet
=> PASS，仅解析
同样占位变量，docker compose -p kube-triage-issue28-gatea-test -f infra/test.compose.yaml --profile repair-mock config --quiet
=> PASS，仅解析
git diff --check
=> PASS
```

额外只读检查：`docker volume ls --filter label=com.docker.compose.project=...` 两个独立项目名均返回空；`apps/web` 差异为空。Sandbox 内 Docker socket 拒绝访问，Host 只读复核成功；未据此推断 Host Docker 缺失。没有启动 Compose、创建卷或触碰现有项目。

## 安全、成本与历史结论

本轮真实 Provider Run 0，Kubernetes 写 0；真实 Token/费用/延迟 UNKNOWN。Aegra SSE/UI E2E、真实 Reader/Repair、真实 Provider Token/延迟、Gate B 摘要策略及额外摘要 Token、真实 A/B 全部 **NOT RUN**。离线估算输入减少不等于 Provider 实际 Token 或费用降低。独立人工 Code Review 尚未完成。

既有 #11 严格 CrashLoop Gate FAIL、#11 人工诊断评分 BLOCKED、#13 G03 PARTIAL FAIL/L3 NOT RUN、#15 B06 FAIL 原样保留；本次测试不能修订这些历史结论。残余风险包括估算与 Provider 分词/隐藏开销不一致、真实 Context Limit 仍可能触发，以及有效但恶意的工具正文仍需真实模型和人工审阅。默认关闭开关降低未验收生产路径的行为变化。
