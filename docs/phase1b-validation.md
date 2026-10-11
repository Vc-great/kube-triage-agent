# Phase 1B 验证记录（2026-10-11）

> 本文件下方原表记录 PR #3 代码阶段的历史执行状态。2026-10-11 独立 Real 执行分支的最新状态见 [phase1b-real-e2e.md](phase1b-real-e2e.md)。原表中的 `origin/main=5d5a124` 是当时的基线；本轮 fetch 后主线为 `59ec23a`。历史 Mock PASS 不代表本轮 Real PASS。

| 本轮 Real 验收项 | 状态 | 证据 |
| --- | --- | --- |
| 正确集群与专属资源归属 | PASS | `k8s-m` → `k8s-master01`，context `kubernetes-admin@kubernetes`，API `192.168.31.136:6443`；目标对象创建前均不存在，创建后有项目标签。用户完成节点代理配置后，本轮只读复核三节点均 Ready |
| ServiceAccount、Role、RoleBinding | PASS | 仅 `kube-triage-demo`，`pods/events get,list`、`pods/log get` |
| Mac Docker 到 API 的 TLS | PASS | 项目 API 容器以 CA 验证 `/livez` 为 HTTP 200；Real MCP 四个调用均用带 CA 的受限 kubeconfig 成功 |
| 受限身份允许与拒绝矩阵 | PASS | 本轮 `kubectl auth can-i` 的 yes/no 与实际跨 Namespace、Secret Forbidden 一致；独立无效 Token 返回 401 |
| 真实 Pod 与 Event API | PASS | 受限 `kubectl` 读取 `triage-sample` 和真实 Event；这不是 MCP 调用 |
| 真实 Pod Log | PASS | 镜像导入项目 Pod 所在节点缓存后，Pod `Succeeded`，受限身份读到两行真实日志 |
| Real MCP 四工具与 Aegra ToolMessage/SSE | PASS | `tools/list` 恰好四个原生只读工具；四次 Real 调用与四条 Aegra HTTP/SSE 命令都返回真实对象，无 Mock 标记 |
| 浏览器 Real 展示 | NOT RUN | 页面需项目 API Key；自动审批拒绝将 Token 写入剪贴板，等待用户手动输入；HTTP/SSE 结果不代替 UI |
| Real 停服恢复、Mock 审批/Checkpoint 运行回归 | PASS | MCP 停止时连接错误、恢复后真实 Pod 读取；更新旧 Mock 镜像后 `scripts/acceptance.py` 全部通过 |
| GitHub CI | PASS | [Draft PR #4](https://github.com/Vc-great/kube-triage-agent/pull/4) 的 `python`、`compose`、`web` 三项均成功 |

状态含义：PASS 为实际通过；FAIL 为实际失败；NOT RUN 为尚未执行。Mock 结果不能代替真实 Kubernetes 验收。

| 范围 | 项目 | 状态 | 证据 / 原因 |
| --- | --- | --- | --- |
| 基线 | `git fetch origin` 与独立分支 | PASS | `origin/main=5d5a124`；`codex/phase1b-k8s-mcp` |
| 上游静态审查 | 固定镜像与字段 | PASS | v0.0.67 README / 同版本配置参考确认四工具名、`tail`、`enabled_tools` 等字段；GHCR manifest 包含 linux/arm64 |
| Compose | 默认与 `--profile real` 静态配置 | PASS | 两次 `docker compose ... config --quiet` 返回 0；不代表 Real 容器启动 |
| Python | pytest | PASS | `uv run --frozen --offline pytest -q`：13 passed |
| Python | ruff | PASS | 修正 import 顺序后复跑 |
| Web | lint / build | PASS | lint：0 error、18 条原有 warning；Next.js build 成功 |
| Mock | 参数、Namespace、额外字段、超时、错误分类 | PASS | 单元测试覆盖；Mock 返回 `mock=true` |
| Mock 协议 | 独立 Streamable HTTP 四项工具调用 | PASS | 临时进程中 `tools/list` 恰好四项；四次 `call_tool()` 均返回 static-fixture；跨 Namespace 在客户端拒绝，直接 MCP 的额外参数返回 `isError=true` |
| Aegra Mock E2E | Auth/Thread/SSE/审批/Checkpoint/重启 | NOT RUN | 宿主机已有同名 `kube-triage-agent` Compose 项目由其它 worktree 管理；不覆盖运行实例 |
| 集群只读预检 | context/API/nodes/namespaces | NOT RUN | `kubectl config current-context` 报未设置 context，无法确定目标 |
| 固定镜像 | 无真实凭据启动、`tools/list` 与 JSON Schema | PASS | 临时容器加载项目 TOML；仅四项工具；`pods_log.tail` Schema 最小值 0，本项目限制 1～100 |
| Real MCP | 项目 SA 凭据下容器启动与 Kubernetes API 连通 | NOT RUN | 项目短期 kubeconfig 尚不存在；未获得集群 context 确认 |
| Real Kubernetes | 本 Namespace Pod/详情/Event/Log | NOT RUN | 未部署项目 SA/RBAC/示例 Pod；无真实凭据 |
| Real Kubernetes | 跨 Namespace/Secret/写拒绝 | NOT RUN | 同上 |
| Real 故障演示 | 断连恢复、Token 过期 | NOT RUN | 同上 |

## 实际执行的安全预检

- `kubectl config current-context`：未设置 context；未调用集群写 API。
- Host Docker 29.7.2、arm64；`docker compose ls` 显示同名项目已有五个运行容器，配置来自其它 worktree。未 stop、up、down、prune 它们。
- 起初本地没有 v0.0.67 镜像；GHCR OCI manifest 证实有 linux/arm64。已拉取固定镜像并用临时无 Token kubeconfig 启动隔离容器，随机绑定 127.0.0.1 端口读取 `tools/list` 后立即停止和删除临时文件；该检查不证明 Kubernetes 连接。
- 使用 0600 的无凭据临时 kubeconfig 再次启动固定镜像，确认本机 Docker Desktop 的非 root 容器可读取只读挂载文件；这不证明其它 Docker Host 的 UID 映射相同。
- 实际 Schema：`pods_list_in_namespace` 必填 `namespace`；`pods_get` 必填 `name`；`pods_log` 必填 `name`，`tail` 默认 100、最小 0；`events_list` 无必填字段。本项目为了 Namespace 隔离全部显式传 `namespace`，日志固定传 `tail=20` 并拒绝 0。
- Draft PR #3 的 CI 三项（python、web、compose）全部通过：[Actions run](https://github.com/Vc-great/kube-triage-agent/actions/runs/38143421115)。

## 获授权后的逐项命令

先确认 `<CONFIRMED_CONTEXT>` 与 `kube-triage-demo` 是本项目实验资源，再执行 README 的人工 bootstrap 步骤。下列命令将产生实际证据，当前均 **NOT RUN**：

```bash
kubectl --context <CONFIRMED_CONTEXT> get nodes
kubectl --context <CONFIRMED_CONTEXT> get ns kube-triage-demo --show-labels
kubectl --context <CONFIRMED_CONTEXT> apply -f infra/k8s/reader.yaml
python3 scripts/refresh-kubeconfig.py --context <CONFIRMED_CONTEXT> --confirm <CONFIRMED_CONTEXT>/kube-triage-demo
KUBECONFIG=.local/kubeconfig kubectl auth can-i list pods -n kube-triage-demo
KUBECONFIG=.local/kubeconfig kubectl auth can-i get pods -n kube-triage-demo
KUBECONFIG=.local/kubeconfig kubectl auth can-i list events -n kube-triage-demo
KUBECONFIG=.local/kubeconfig kubectl auth can-i get pods/log -n kube-triage-demo
KUBECONFIG=.local/kubeconfig kubectl auth can-i list pods -n default
KUBECONFIG=.local/kubeconfig kubectl auth can-i get secrets -n kube-triage-demo
KUBECONFIG=.local/kubeconfig kubectl auth can-i create pods -n kube-triage-demo
MCP_SERVER_URL=http://k8s-mcp:8080/mcp ./scripts/compose.sh --profile real up -d --build --wait
```

运行后须从项目内 API 容器使用 MCP SDK 对 `http://k8s-mcp:8080/mcp` 再执行 `tools/list`，确认实际项目实例仍恰好四项。随后在浏览器依次执行四个命令，核对 ToolMessage/SSE 真实对象名与无 `mock=true`。用同一受限 kubeconfig 确认跨 Namespace、Secret 和写操作被拒绝。停本项目 `k8s-mcp` 后检查连接错误，恢复后重试；Token 过期时检查认证错误。证据只保留工具名、Namespace、对象名、状态和 PASS/FAIL，不保存 Token、kubeconfig 或日志正文。

若 API Server 仅 Host 可达，先确认 Docker 容器到其 HTTPS 地址可达；不能以 Host `kubectl` 成功替代容器链路结果。
