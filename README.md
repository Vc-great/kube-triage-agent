# kube-triage-agent：正式 Real，Mock 仅供测试

dev01 完整部署与 Mac 原生开发见 [部署与开发指南](docs/dev01-deployment.md)：`make dev-web` 只调前端并连接远端 API；`make dev` 使用真实 Reader、受控 Repair、Memory 与 Context；`make dev-mock`、`make dev-memory-*` 和 `make dev-mock-{window,summary}` 用于人工场景测试。切换前执行 `make dev-stop`。本机 Compose 与原生开发共用根目录私有 `.env`（0600）；场景由命令决定。

`make dev-deep-demo` 启动隔离的 [Deep Agents Core Demo](docs/issue41-p0-demo.md)：真实 CPA `gpt-6-luna` + 合成 Mock Reader、Planning ON/OFF，固定 Chat Completions，默认关闭 Trace。它直连已批准的 CPA LAN 目标，不经过 7890 代理。

`make dev-deep-review-demo` 启动独立的 [Evidence Reviewer Demo](docs/issue72-reviewer-demo-v2.md)：双 FakeModel + 合成 Mock Reader → 原生 `task(evidence-reviewer)` → 中文第二意见；仅测试环境，默认端口 Web 13072 / API 12072 / PG 15472。

其余 API 模式的模型请求均通过所在宿主机 7890 代理；Compose 容器统一使用 `host.docker.internal:7890`。Langfuse Trace 见 [Issue #39 配置与隐私说明](docs/issue39-langfuse-observability.md)和[验收记录](docs/issue39-langfuse-validation.md)。对应机器根目录 `.env` 中有完整有效 Key 时自动开启，导出也走同一代理；真实 Reader、Memory 和 dev01 模式可能向云端发送 Kubernetes 或会话数据。

单用户 AI 全栈学习与面试 Demo：Aegra Thread/Run/SSE/Checkpoint + LangGraph + 原生 Reader MCP。正式自然语言诊断恒走真实 OpenAI 兼容 LLM → 四个只读 MCP 工具 → Kubernetes API，Namespace 固定为 `kube-triage-demo`。缺配置、未批准 Reader URL 和生产模拟配置均 Fail Closed；无 Echo、固定命令或 Mock 回退。

## AI 规划与 AO 执行

中大型开发任务采用 [轻量 SDD 工作流](docs/agent-workflow.md)：网页 ChatGPT 先核对 Issue、代码与已有 PR，提交纯文档 Planning PR；设计合入 `main` 后，由 AO 使用短提示词调度 Codex 从 [计划目录](docs/plans/README.md) 读取设计、按阶段实现与验收。长期 Agent 约束见 [AGENTS.md](AGENTS.md)，新方案可复制 [计划模板](docs/plans/TEMPLATE.md)。小型修复继续使用 Issue → 实施 PR，无需强制额外文档。

## 独立项目快速启动

先只读核对 Docker 项目标签、端口与资源归属。不要用新 Worktree 操作稳定 `kube-triage-agent` 或 `ragflow-lab`。

```bash
./scripts/start.sh --init-only
# 私下编辑 .env：填写 LLM_MODEL、LLM_API_KEY，可选 LLM_BASE_URL。
# 将已获准且有效的受限 Reader kubeconfig 放入 .local/kubeconfig，目录 0700、文件 0600。
# 默认独立端口 12027/13002；确认空闲后再启动。
export COMPOSE_PROJECT_NAME=kube-triage-real-default-review
./scripts/start.sh
python3 scripts/acceptance.py --project "$COMPOSE_PROJECT_NAME" --env-file .env --api-base http://127.0.0.1:12027
```

API Key 为私有 `.env` 的 `DEMO_API_TOKEN`，只在本机 Web 输入。模型 Key 不进入 Web。初始化只在 `.env` 不存在时创建随机数据库密码和 API Token（0600）；已有文件不改写。正式 Compose 固定 `TRIAGE_ENV=production`，默认 URL `http://k8s-mcp:8080/mcp`，无需 `real` profile，Reader 默认启动。详细检查和错误边界见 [部署](docs/deployment.md)、[架构](docs/architecture.md)、[隔离](docs/isolation.md)。

正常提问示例：`请只读调查 kube-triage-demo 当前 Pod 与事件，依据证据用中文说明现象、推测和人工建议。` 不假设集群存在故障 Pod。`/repair-demo` 仍是唯一固定 HITL 入口；正式 API 默认 `REPAIR_ENABLED=false`，本机 `make dev` 开启真实 Repair，但只有用户审阅固定目标与 UID 并批准有效的 0→1 提案后才会写入。LLM 不绑定写工具。

## 可重复的离线测试

Issue #78 的 [Conversation History / Evidence Store 离线 Demo](docs/issue78-demo.md) 使用测试专用 FakeModel、Mock MCP 和独立 PostgreSQL，提供显式迁移、Evidence ID 回查、Web 刷新历史与开关回退；[实测报告](docs/issue78-validation.md)逐项记录验收状态。新增业务持久化默认关闭，不改变正式 Reader/Repair/Memory 授权。

本地 FakeModel 不影响正式 Agent 使用真实 LLM。FakeModel 验证标准 Tool Calling 协议、预算与策略；Mock 和 Fixtures 验证契约；Golden 保存合成评测的已知事实。

```bash
cd server
uv sync --frozen --python 3.13
uv run --frozen ruff check src tests
uv run --frozen pytest -q
cd ../apps/web
pnpm install --offline --frozen-lockfile
pnpm lint
pnpm build
```

显式 Mock 联调只用独立 `infra/test.compose.yaml`，不可与正式文件叠加。准备私有 `.local/phase3a.env`（`TRIAGE_ENV=test`、真实模型配置、独立密码/Token、独立端口，API Reader URL 由测试文件固定到 Mock）：

```bash
docker compose -p kube-triage-real-default-eval --env-file .local/phase3a.env -f infra/test.compose.yaml up -d --build postgres redis mock-mcp api
python3 scripts/eval_phase3a.py --dry-run
# 经确认需重新做合成评测才运行以下命令；新目录，不覆盖历史证据：
python3 scripts/eval_phase3a.py --env-file .local/phase3a.env --out .local/eval-runs/new-test-only --api-base http://127.0.0.1:12028
```

离线 Repair Gate A 用同一测试文件加 `--profile repair-mock`，私有 `.local/phase3b.env` 明确 `TRIAGE_ENV=test`、`REPAIR_ENABLED=true`、`REPAIR_SIMULATED=true`，再运行 `scripts/acceptance_phase3b.py`。提案和结果必须 `simulated=true`，仅改变独立 Mock 的内存，不能证明真实修复。无模型凭据时跑 pytest；不恢复旧 Echo。

## 当前验收与历史边界

[Issue #16 Roadmap 总验收索引](docs/issue16-roadmap-closeout.md)汇总五项能力的证明等级、历史证据和未闭环 Gate。

[Issue #11 Gate B2 只读收口补记](docs/issue11-gateb2-final-report.md)记录历史严格 Gate、当前证据及本轮停止条件。
[Issue #11 Gate B2 后续只读复核](docs/issue11-gateb2-completion.md)记录 Healthy 的有界快照、Node 重启证据、development Runtime 恢复与 ImagePull 授权门禁。

Issue #11 的未部署 Gate A 草案见 [三个真实故障 Scenario](docs/issue11-scenarios.md)与[只读预检/验收矩阵](docs/issue11-gatea-validation.md)；先前只读现状见 [Gate B1 预检](docs/issue11-gateb-real-e2e.md)。[Luna High M1/M2 实测记录](docs/issue11-m1-m2-real-e2e.md)说明本轮 M1 失败后的停止点与未创建的三个 Pod。

Issue #12 的独立 Mock 盲样、test-only Prompt A/B 和真实模型授权门禁见[实验设计](docs/issue12-design.md)与[评估报告](docs/issue12-evaluation-report.md)。未获模型数据发送授权前只运行 `python3 scripts/eval_issue12.py --out .local/eval-runs/issue12-dry-plan --dry-run`；人工评分模板见[Issue #12 Rubric](docs/issue12-human-rubric.md)。

Issue #14 复用既有私有评测轨迹进行纯离线 Token、工具、Runner 耗时与成本可得性统计；口径见[指标设计](docs/issue14-metrics-design.md)，当前来源覆盖与门禁见[验收记录](docs/issue14-metrics-validation.md)。

Issue #15 的真实 HITL 历史、B06=FAIL 与证据边界见[证据包](docs/issue15-hitl-evidence.md)；无新写入展示见[只读手册](docs/issue15-hitl-readonly-demo.md)。

当前 A01–A15、实际失败/阻塞、文件清单和面试复盘见 [Real-by-default 验收](docs/real-by-default-review.md)。`docs/phase*` 是各阶段历史记录，其旧命令和默认架构不代表当前启动方式。Phase 3A 12 次原分母、人工 Grounding、Golden 与 [历史报告](docs/phase3a-report.md) 保留；[Phase 3B Gate B](docs/phase3b-gateb-real-e2e.md) 的 B06=FAIL 保留。旧模拟审批 Checkpoint 不转换为真实写入：只读查看历史，为新诊断新建 Thread。



## 本地启动
```commandline
cd /Users/vc/code/kube-triage-agent
make dev-stop
make dev-web   # 只调前端，连接 dev01 API
# 或
make dev       # 真实 Reader、Memory、Context 与受审批保护的 Repair
```
