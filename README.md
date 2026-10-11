# kube-triage-agent — Phase 1B Demo

单用户本机演示：Aegra 鉴权、LangGraph 确定性命令、原生 Kubernetes MCP 只读工具。默认使用独立 Mock MCP；Real 模式使用项目专属短期 ServiceAccount kubeconfig。没有 LLM、诊断推理或自动修复。

## 默认 Mock

```bash
make up       # 首次生成项目私有 .env；仅管理 -p kube-triage-agent
make ps
make check
make down     # 仅停本项目容器，保留数据卷
```

打开 [Web](http://localhost:13000)，输入本项目 `.env` 的 `DEMO_API_TOKEN`。可试 `pods kube-triage-demo`、`pod kube-triage-demo healthy-pod`、`events kube-triage-demo`、`logs kube-triage-demo crashloop-pod`。Mock 输出含 `mock=true`；`/approve-demo` 仍只模拟审批。API 绑定 `127.0.0.1:12026`，MCP、PostgreSQL、Redis 没有宿主机端口。

## 授权后启用 Real

先只读检查目标：`kubectl config current-context`、`kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'`、`kubectl get nodes`、`kubectl get ns`。确认 context、API 地址、`kube-triage-demo` 归属和 Docker 容器可达性。**只有在确认正确 context 与项目资源后**，人工 bootstrap 身份才执行：

```bash
kubectl --context <CONFIRMED_CONTEXT> apply -f infra/k8s/reader.yaml
# 可选：kubectl --context <CONFIRMED_CONTEXT> apply -f infra/k8s/triage-sample.yaml
python3 scripts/refresh-kubeconfig.py --context <CONFIRMED_CONTEXT> --confirm <CONFIRMED_CONTEXT>/kube-triage-demo
```

脚本申请约 24 小时短期 Token；实际 TTL 由集群决定。它只写 Git 忽略的 `.local/kubeconfig`（0600），不会显示 Token。过期时以同样命令手工轮换，再用 `MCP_SERVER_URL=http://k8s-mcp:8080/mcp ./scripts/compose.sh --profile real up -d --force-recreate k8s-mcp` 重建本项目 MCP 容器，使只读文件挂载更新。不要挂载管理员 kubeconfig。先以 `KUBECONFIG=.local/kubeconfig kubectl auth can-i` 验证本 Namespace Pod/Event/Log 读取为 yes，跨 Namespace、Secret、写操作为 no。容器内部必须能访问 kubeconfig 中的 HTTPS API Server；Host 可达不等于容器可达。

```bash
MCP_SERVER_URL=http://k8s-mcp:8080/mcp ./scripts/compose.sh --profile real up -d --build --wait
```

Real 模式镜像固定为 `ghcr.io/containers/kubernetes-mcp-server:v0.0.67`，不发布宿主机端口。直接启动前须确保本项目没有另一个 worktree 正在用同一个 Compose project，以免覆盖该实例。关闭只用 `./scripts/compose.sh --profile real down`；这不会删除卷。清理集群资源须再次核对 context，由人工执行 `kubectl --context <CONFIRMED_CONTEXT> delete -f infra/k8s/triage-sample.yaml`（若曾应用）和 `kubectl --context <CONFIRMED_CONTEXT> delete -f infra/k8s/reader.yaml`，随后删除本项目 `.local/kubeconfig`。这些操作不会触及其它项目。

开发检查：`cd server && uv sync --frozen --python 3.13 && uv run --frozen ruff check src tests && uv run --frozen pytest -q`；`cd apps/web && pnpm install --frozen-lockfile && pnpm lint && pnpm build`。

设计与验收：[Phase 1B 设计](docs/phase1b-design.md)、[验证记录](docs/phase1b-validation.md)、[面试问答](docs/phase1b-interview.md)。历史：[Phase 1A 设计](docs/phase1a-design.md)、[隔离说明](docs/isolation.md)。
