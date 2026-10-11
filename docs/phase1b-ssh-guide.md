# Phase 1B SSH 最短操作手册

此手册用于个人学习集群 `ssh k8s-m` 和项目 `kube-triage-agent`。所有 Compose 命令从已核实的稳定主工作树 `/Users/vc/code/kube-triage-agent` 执行；先前混合的旧 worktree 来源及本轮受控迁移见 [执行记录](phase1b-real-e2e.md)。不要从新 worktree 直接覆盖运行项目。

## 1. 只读确认并初始化

```bash
git fetch origin
ssh k8s-m 'hostname; kubectl config current-context; kubectl cluster-info; kubectl get nodes -o wide'
ssh k8s-m 'kubectl get ns kube-triage-demo --show-labels'
ssh k8s-m 'kubectl -n kube-triage-demo get serviceaccount,role,rolebinding,pod --show-labels'
docker compose ls
docker ps --filter label=com.docker.compose.project=kube-triage-agent
```

核对目标确为个人学习集群；若对象已存在，确认每个项目对象的 `app.kubernetes.io/part-of=kube-triage-agent` 与规则匹配。身份或归属不清时停止写入。确认无冲突后，仅引导专属只读身份：

```bash
ssh k8s-m 'kubectl apply -f -' < infra/k8s/reader.yaml
python3 scripts/refresh-kubeconfig.py --ssh-host k8s-m --confirm k8s-m/kube-triage-demo
stat -f '%Sp %N' .local .local/kubeconfig
KUBECONFIG=.local/kubeconfig kubectl auth can-i list pods -n kube-triage-demo
KUBECONFIG=.local/kubeconfig kubectl auth can-i list pods -n default
```

预期前者 yes、后者 no。脚本还保留本机 `--context NAME --confirm NAME/kube-triage-demo` 路径。Token 有效期 24h；刷新时重跑脚本并只重建本项目的 `k8s-mcp` 容器。不要输出 `.local/kubeconfig`、传入管理员 kubeconfig、关闭 TLS 校验或把 Token 放入 `.env`。

## 2. Real / Mock 切换

先在稳定运行目录核对 `.env`、`.local/kubeconfig` 为普通文件、Compose 归属和服务 ID；执行 `./scripts/compose.sh --profile real config --quiet`。这些命令仅在目录归属确认后使用：

```bash
MCP_SERVER_URL=http://k8s-mcp:8080/mcp ./scripts/compose.sh --profile real up -d --build --wait
# 在浏览器打开本机 127.0.0.1 Web 端口，执行 pods / pod / events / logs 命令。
# 仅停止 Real MCP，保留 Postgres/Redis 数据：
./scripts/compose.sh --profile real stop k8s-mcp
# 恢复：
./scripts/compose.sh --profile real up -d k8s-mcp
# 切回 Mock，确保 API 重建后重新读取 MCP_SERVER_URL：
MCP_SERVER_URL=http://mock-mcp:8000/mcp ./scripts/compose.sh up -d --no-deps --force-recreate api
```

Mock 回归用 `python3 scripts/acceptance.py`，它包含静态 fixture 和 `/approve-demo`，不能当作 Real 验收。Real 的四工具调用与 TLS/RBAC 结果应逐项记录，不能用 `tools/list` 代替真实读取。本轮已执行启动、MCP 停止/恢复、Mock 切换与回归，并最终把 API 切回 Real。

## 3. 项目资源清理（仅获单独授权时执行）

先核对对象标签、作用域与当前工作负载；本轮没有授权删除，下面命令**未执行**：

```bash
ssh k8s-m 'kubectl -n kube-triage-demo get pod triage-sample --show-labels'
ssh k8s-m 'kubectl get ns kube-triage-demo --show-labels'
ssh k8s-m 'kubectl delete -f -' < infra/k8s/triage-sample.yaml
ssh k8s-m 'kubectl delete -f -' < infra/k8s/reader.yaml
```

不要使用 `docker compose down --volumes`、全局 prune、跨项目清理或删除其它 Namespace。
