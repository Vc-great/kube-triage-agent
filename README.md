# kube-triage-agent — Phase 2 Demo

单用户学习项目：Aegra + LangGraph + 四个原生 Kubernetes MCP 只读工具。`LLM_ENABLED=false`（默认）保留 Phase 1B Mock 命令；`true` 使用实际支持标准 Tool Calling 的 OpenAI 兼容模型，自主选择工具并给出中文证据报告。没有自动修复。

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
