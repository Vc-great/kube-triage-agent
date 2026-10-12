# kube-triage-agent — Phase 2 Demo

单用户学习项目：Aegra + LangGraph + 四个原生 Kubernetes MCP 只读工具。`LLM_ENABLED=false`（默认）保留 Phase 1B Mock 命令；`true` 使用实际支持标准 Tool Calling 的 OpenAI 兼容模型，自主选择工具并给出中文证据报告。没有自动修复。

## Phase 3B：受控 0→1 演练

默认 `REPAIR_ENABLED=false`，`/repair-demo` 不会写 Kubernetes。唯一固定目标是 `kube-triage-demo/Deployment/triage-repair-demo`，预期从 0 扩到 1。模型仍只有原四个只读工具；网页必须在同一 Aegra Thread 审批含 `proposal_id` 的提案。0→1 不代表 Pod Ready，更不代表 CrashLoop/OOM 根因得到修复。设计、实际验收与面试问答见 [设计](docs/phase3b-design.md)、[验证](docs/phase3b-validation.md)、[问答](docs/phase3b-interview.md)。

**离线模拟**：在此 Worktree 创建私有 `.local/phase3b.env`（独立数据库密码和 API Token，端口 12027/13001，`LLM_ENABLED=false`、`REPAIR_ENABLED=true`、`REPAIR_SIMULATED=true`、`REPAIR_MCP_SERVER_URL=http://mock-repair-mcp:8001/mcp`）。仅用独立项目运行：

```bash
docker compose -p kube-triage-phase3b-demo --profile repair-mock --env-file .local/phase3b.env -f infra/compose.yaml up -d --build --wait postgres redis mock-mcp mock-repair-mcp api web
python3 scripts/acceptance_phase3b.py
```

模拟提案和结果带 `simulated=true`；Mock 的写入只改变其进程内存。切勿将模拟结果写成真实集群恢复。

**真实演练准备（须另获单独授权后执行）**：先只读确认 `ssh k8s-m` 所指集群、命名空间和同名对象。若同名 Deployment 已存在且归属标签或内容不符，停止。获明确授权后才可应用**仅** `infra/k8s/repair-demo.yaml` 与 `infra/k8s/repair-rbac.yaml`，并生成短期凭据：

```bash
ssh k8s-m 'kubectl apply -f -' < infra/k8s/repair-demo.yaml
ssh k8s-m 'kubectl apply -f -' < infra/k8s/repair-rbac.yaml
python3 scripts/refresh-kubeconfig.py --ssh-host k8s-m --account kube-triage-repairer --confirm k8s-m/kube-triage-demo/kube-triage-repairer
```

私有 `.local/repair-kubeconfig` 权限为 0600。真实启动必须使用独立项目、`--profile repair`、`-f infra/compose.yaml -f infra/repair-api.compose.yaml`，设置 `REPAIR_ENABLED=true`、`REPAIR_SIMULATED=false`、`REPAIR_MCP_SERVER_URL=http://repair-mcp:8080/mcp`、`MCP_SERVER_URL=http://k8s-mcp:8080/mcp`，并有 Reader 私有凭据；`repair-mcp` 只有一个原生 `resources_scale` 工具，不发布宿主机端口。用户须在网页亲自 Approve。此处只记载手工步骤，本轮没有获得真实集群写入授权。

停止模拟项目可手工运行相同 `-p/--profile/--env-file/-f` 前缀加 `down`；任何卷删除、集群 scale 回退或资源删除都需单独核对和确认，不能自动执行。

## 本 worktree 的安全启动

稳定 Compose 项目位于 `/Users/vc/code/kube-triage-agent`。**不要从新 worktree 用固定项目名 `kube-triage-agent` 执行 up/down/build**。本地离线开发只需：

```bash
cd server
uv sync --frozen --python 3.13
uv run --frozen ruff check src tests
uv run --frozen pytest -q
```

如需独立 Compose 联调，先准备此 worktree 私有 `.env`（复制 `.env.example`，设置本项目独立密码和 Token），使用独立项目名和回环端口，例如 `COMPOSE_PROJECT_NAME=kube-triage-phase2 API_PORT=12027 WEB_PORT=13001 NEXT_PUBLIC_API_URL=http://localhost:12027 docker compose -f infra/compose.yaml up -d --build`。具名卷会跟随项目名隔离。清理仅对这个项目执行同样前缀加 `down`，不要加 `--volumes`。Web 的 Aegra API Key 是 `DEMO_API_TOKEN`，只在本地浏览器输入；模型 Key 只进入 API 容器。

## LLM 配置

`.env` 中设置 `LLM_ENABLED=true`、`LLM_MODEL`、`LLM_API_KEY`；自托管 OpenAI 兼容服务可选设置 `LLM_BASE_URL`。确认供应商真实支持标准 Tool Calling，并从 **API 容器内部**检查 URL 可达性；`localhost` 指向容器本身。缺模型名或 Key 会返回明确配置错误，不能以 Mock 结果冒充。无 Key 可保留 `false`，旧命令如 `pod kube-triage-demo crashloop-pod` 仍可用。真实 Agent 示例：`kube-triage-demo 中的 crashloop-pod 为什么一直重启？请自主调查。`

Real Kubernetes 路径、受限 ServiceAccount 和 TLS 校验见 [Phase 1B Real E2E](docs/phase1b-real-e2e.md)；仅查询已有资源，`triage-sample` 是正常 Pod。Phase 2 的实际验收结论见 [验证记录](docs/phase2-validation.md)，架构见 [设计](docs/phase2-design.md)，面试复习见 [问答](docs/phase2-interview.md)。

## Phase 3A：合成数据诊断评测

在**独立** Compose 项目中准备私有 `.local/phase3a.env`（`LLM_ENABLED=true`、现有已批准的模型配置、独立数据库密码和 API Token，`MCP_SERVER_URL=http://mock-mcp:8000/mcp`；不要提交或打印密钥），仅启动 `postgres redis api mock-mcp`。不要从此 Worktree 使用硬编码项目名的 `scripts/compose.sh`，也不要连接真实 Kubernetes。

```bash
docker compose -p kube-triage-phase3a-eval --env-file .local/phase3a.env -f infra/compose.yaml up -d --build postgres redis mock-mcp api
python3 scripts/eval_phase3a.py --cases eval/cases.json --repeats 3 --out .local/eval-runs/phase3a-baseline --env-file .local/phase3a.env
```

先用 `--dry-run` 只校验 Golden；它不产生真实分数。Runner 写入 Git 忽略的私有证据与 `reviews.json` 待人工评分。数据流与公式见 [设计](docs/phase3a-design.md)，本轮 12 次结果见 [报告](docs/phase3a-report.md)，面试复习见 [问答](docs/phase3a-interview.md)。
