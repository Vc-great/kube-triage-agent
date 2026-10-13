# kube-triage-agent：正式 Real，Mock 仅供测试

dev01 完整部署与 Mac 原生开发见 [部署与开发指南](docs/dev01-deployment.md)：`make dev-web` 只调前端并连接远端 API；`make dev` 联调本地前后端并连接远端独立开发数据；切换前执行 `make dev-stop`。

单用户 AI 全栈学习与面试 Demo：Aegra Thread/Run/SSE/Checkpoint + LangGraph + 原生 Reader MCP。正式自然语言诊断恒走真实 OpenAI 兼容 LLM → 四个只读 MCP 工具 → Kubernetes API，Namespace 固定为 `kube-triage-demo`。缺配置、未批准 Reader URL 和生产模拟配置均 Fail Closed；无 Echo、固定命令或 Mock 回退。

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

正常提问示例：`请只读调查 kube-triage-demo 当前 Pod 与事件，依据证据用中文说明现象、推测和人工建议。` 不假设集群存在故障 Pod。`/repair-demo` 仍是唯一固定 HITL 入口，默认 `REPAIR_ENABLED=false`，本次不授权真实修复；LLM 不绑定写工具。

## 可重复的离线测试

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

Issue #11 的未部署 Gate A 草案见 [三个真实故障 Scenario](docs/issue11-scenarios.md)与[只读预检/验收矩阵](docs/issue11-gatea-validation.md)；最新只读现状与授权边界见 [Gate B1 预检](docs/issue11-gateb-real-e2e.md)。真实部署须另经 Gate B 批准。

当前 A01–A15、实际失败/阻塞、文件清单和面试复盘见 [Real-by-default 验收](docs/real-by-default-review.md)。`docs/phase*` 是各阶段历史记录，其旧命令和默认架构不代表当前启动方式。Phase 3A 12 次原分母、人工 Grounding、Golden 与 [历史报告](docs/phase3a-report.md) 保留；[Phase 3B Gate B](docs/phase3b-gateb-real-e2e.md) 的 B06=FAIL 保留。旧模拟审批 Checkpoint 不转换为真实写入：只读查看历史，为新诊断新建 Thread。



## 本地启动
```commandline
cd /Users/vc/code/kube-triage-agent
make dev-stop
make dev-web   # 只调前端，连接 dev01 API
# 或
make dev       # 本地前后端联调
```
