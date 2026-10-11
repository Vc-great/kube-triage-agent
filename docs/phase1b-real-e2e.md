# Phase 1B Real Kubernetes 执行记录（2026-10-11）

**结论：Real MCP + Aegra HTTP/SSE PASS；浏览器展示 NOT RUN。** 个人学习集群的受限身份、TLS、RBAC、四个原生 Real 工具、ToolMessage/SSE 和 Mock/审批/Checkpoint 回归均有实际证据。浏览器页面需要项目 API Key，自动审批拒绝把 Token 放入系统剪贴板；本轮没有把 HTTP 结果冒充浏览器结果。

状态含义：PASS 为本轮实际成功；FAIL 为实际请求失败；NOT RUN 为未执行；BLOCKED 为前置条件不满足。命令中的 kubeconfig 内容、Token 和日志正文不进入记录。

## 集群与资源

- Host Git/SSH 的 `git fetch origin`：`origin/main=59ec23a0bcd07c25b257d7a7ebdd83ccd28845d8`，本轮分支 `codex/phase1b-real-e2e`。
- `ssh k8s-m` 的主机名为 `k8s-master01`，`kubectl config current-context` 为 `kubernetes-admin@kubernetes`；`kubectl cluster-info` 指向 `https://192.168.31.136:6443`。节点为 `k8s-master01` Ready、`k8s-node01` Ready、`k8s-node02` NotReady。SSH 别名和这组三节点与用户指定的个人学习集群相符。
- 写入前对 `kube-triage-demo` Namespace、同名 ServiceAccount、Role、RoleBinding 和 `triage-sample` Pod 的 `kubectl get` 均返回 NotFound。随后只执行 `ssh k8s-m 'kubectl apply -f -' < infra/k8s/reader.yaml`；四个对象均报告 created，三类命名空间对象的 `app.kubernetes.io/part-of` 标签均为 `kube-triage-agent`。
- Namespace 没有 Pod 后，单独执行 `ssh k8s-m 'kubectl apply -f -' < infra/k8s/triage-sample.yaml`；Pod 报告 created，位于 `k8s-node01` 且有相同归属标签。未更改其它 Namespace 或工作负载。

## 网络与凭据

| 检查 | 状态 | 实际结果 |
| --- | --- | --- |
| SSH 管理入口 | PASS | 远端 `kubectl cluster-info`、节点和对象读取成功 |
| Mac → API TCP | PASS | `nc -G 3 -vz 192.168.31.136 6443` 成功 |
| Mac Docker → API TCP | PASS | 现有项目 API 容器内 Python socket 连接 `192.168.31.136:6443` 成功 |
| Mac Docker → API TLS | PASS | 将仅 CA 证书经 stdin 交给项目 API 容器，用 Python 默认验证器请求 `https://192.168.31.136:6443/livez`，HTTP 200；未关闭证书校验，未向该容器发送 Token |
| Real MCP → API TLS | PASS | `k8s-mcp` 使用包含 CA 的受限 kubeconfig，四个真实工具调用均成功；无 insecure TLS 配置 |

`python3 scripts/refresh-kubeconfig.py --ssh-host k8s-m --confirm k8s-m/kube-triage-demo` 成功。远端只在本机进程内解析 bootstrap kubeconfig，经 SSH 只传非秘密 server/CA 与新签发的 24h ServiceAccount Token；Mac 上原子写入单一 cluster/context/user 的 `.local/kubeconfig`。实测目录 `0700`、文件 `0600`，`current-context=kube-triage-reader`。未输出或提交 Token。

## RBAC 与真实 Kubernetes API

以下 `KUBECONFIG=.local/kubeconfig kubectl auth can-i …` 均由受限身份执行；`no` 是预期拒绝。

| 操作 | 结果 |
| --- | --- |
| `list/get pods`、`list events`、`get pods/log` in `kube-triage-demo` | PASS：yes |
| `list pods` in `default`、`kube-system` | PASS：no |
| `get/list secrets` in `kube-triage-demo` | PASS：no |
| `create/delete/patch pods` in `kube-triage-demo` | PASS：no |
| 用受限身份实际 `get pods -n default`、`get secrets -n kube-triage-demo` | PASS：Kubernetes 均返回 Forbidden |
| 用独立的故意失效 Token 请求项目 Pod API | PASS：经同一 CA 验证后返回 HTTP 401；有效 kubeconfig 未修改 |

真实读取：`kubectl get pods -n kube-triage-demo` 先返回空列表，创建样例后 `kubectl get pod triage-sample` 返回真实对象；`kubectl get events -n kube-triage-demo` 返回 Scheduled、Pulling 和 Failed 等真实 Event。起初 `kubectl logs` 因 `ImagePullBackOff` 返回 BadRequest。代理调整后，Mac 成功拉取精确的 linux/amd64 `busybox:1.36.1`（digest `sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662`），经 SSH 流式导入 `k8s-node01` containerd 缓存。现有 Pod 自动重试并 `Succeeded`；受限身份读取到 `triage sample: started` 和 `triage sample: complete`。没有删除 Pod 或更改其它工作负载。

上述是 **kubectl → Kubernetes API** 的独立证据；下一节记录 MCP 工具本身的 Real 调用。

## Compose 归属、Real 工具与 Aegra

最初 `docker compose ls` 显示项目五容器：API/Web/Mock 来自旧 `ab8e` worktree，Postgres/Redis 来自已不存在的 `2b14` 目录；所有容器、两个命名卷和私有网络的项目标签均为 `kube-triage-agent`。未从新 worktree 盲目启动。先把干净的主工作树 `/Users/vc/code/kube-triage-agent` 快进到 `origin/main=59ec23a`，把同项目 `.env` 与受限 kubeconfig 以 `0600` 放在主工作树，选它作为后续唯一 Compose 操作目录。`MCP_SERVER_URL=http://k8s-mcp:8080/mcp ./scripts/compose.sh --profile real config --quiet` 成功。

仅启动本项目第六服务 `k8s-mcp`，随后 `--no-deps --build --force-recreate api` 指向 Real。Postgres、Redis、Web 的容器 ID 与事前相同；其它项目 `ragflow-lab` 五容器的 ID/状态也未变化。Mock 容器后来因旧 Phase 1A 镜像只有三个旧工具名而单独重建；未触及数据卷。

在项目 API 容器内使用 MCP Streamable HTTP Session：`tools/list` **恰好** `events_list,pods_get,pods_list_in_namespace,pods_log`，没有写工具。四次单独 `tools/call` 的结果如下；全部 `isError=False` 且没有 `mock=true` / `static-fixture`：

| 原生工具 | 参数（脱敏） | 真实结果 |
| --- | --- | --- |
| `pods_list_in_namespace` | `namespace=kube-triage-demo` | 包含 `triage-sample` |
| `pods_get` | `namespace=kube-triage-demo,name=triage-sample` | 返回该 Pod 详情 |
| `events_list` | `namespace=kube-triage-demo` | 包含该 Pod 的真实调度/拉取 Event |
| `pods_log` | `namespace=kube-triage-demo,name=triage-sample,tail=20` | 包含 `triage sample: complete` |

另以项目 API 的本地 Aegra HTTP/SSE 对四条用户命令分别新建 Thread、发起 Run、读取 State；每条的 Graph `tool_calls` 名称正确、对应 ToolMessage 存在、SSE 有 `data:`、结果含真实对象/日志且无 Mock 标记。UI 页面打开到 Agent Chat 的 API Key 输入页；自动审批拒绝将 Token 写入系统剪贴板，故**浏览器结果 NOT RUN**，与 HTTP/SSE PASS 分开记录。

## 负面测试与回归

| 验收 | 状态 | 实际证据 |
| --- | --- | --- |
| `pods default`、`pods kube-system` | PASS | Real Aegra/SSE 的 State 均有 `Namespace denied` |
| RBAC 跨 Namespace、Secret、写入拒绝 | PASS | 上表受限身份矩阵及真实 Forbidden；MCP 只暴露四读工具 |
| 无效 Token | PASS（API 层） | 独立失效 Token 经同一 CA 验证后得到 HTTP 401；没有修改有效凭据。MCP/UI 的 401 展示 NOT RUN |
| MCP 停服/恢复 | PASS | 仅 stop 项目 `k8s-mcp` 一次，Aegra ToolMessage/SSE 展示连接失败；重新 up 后再次读到 `triage-sample` |
| Mock/审批/Checkpoint | PASS | 切 API 至 Mock 后，首次验收因旧 Phase 1A Mock 工具名失败；仅重建项目 `mock-mcp` 后 `python3 scripts/acceptance.py` 全部 PASS，包括 Auth、SSE、`/approve-demo` approve/reject、API 重启与线程历史持久化 |
| 最终服务状态 | PASS | API 已切回 Real，六个项目容器运行；Postgres/Redis/Web ID 不变，其它项目容器 ID/状态不变 |
| 浏览器 Real 展示 | NOT RUN | 本地页面需要 API Key，自动审批拒绝系统剪贴板传递；待用户手动输入后可复核 |

本轮静态回归：`uv run --python 3.13 --frozen --offline ruff check src tests` 全部通过，`pytest -q` 为 13 passed；`python3 -m py_compile scripts/refresh-kubeconfig.py`、`git diff --check`、Real Compose `config --quiet` 通过。首次未指定 Python 版本时选中 3.14，离线缓存缺少对应 `grpcio`；按仓库 README 改用已有 3.13 后成功。Web build 未重跑（Web 源码未改）；GitHub CI 待本轮 Draft PR 建立后核对。

浏览器展示是尚缺的硬性证据。任何集群资源清理或删除仍需另行授权。
