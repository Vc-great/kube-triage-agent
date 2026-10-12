# Phase 3B Gate B：真实 Kubernetes HITL 验收记录

日期：2026-10-12（北京时间）。基线：实时 `origin/main=010d8f4727472cd700c64861d8b834576909e784`，工作分支 `codex/phase3b-gateb-real-e2e`，Codex 管理的独立 worktree。结论：**真实 0→1 已发生，Pod 最终 Ready；严格 Gate B 为部分通过（B06 流程偏差）**。本次没有调用真实 LLM，`LLM_ENABLED=false`。

## 身份、授权与隔离

- 只读 SSH 到 `k8s-m` 实际落在 `k8s-master01`，Context 为 `kubernetes-admin@kubernetes`；API Server 为内网 HTTPS `192.168.31.xxx:6443`。三个 v1.36.5 节点均 Ready。`kube-triage-demo` Namespace 已存在，带 `app.kubernetes.io/part-of=kube-triage-agent`；现有 Reader SA/Role/RoleBinding 与样例 Pod 也带项目标签。
- B01 时 `triage-repair-demo` Deployment 及同名 Repairer SA/Role/RoleBinding 都不存在。清单未偏离基线：`repair-rbac.yaml` 仅定义专用 SA、Role、RoleBinding；`repair-demo.yaml` 仅定义初始 `replicas: 0`、`busybox:1.36.1` 的 Deployment，无 hostPath、特权容器、宿主网络或 Secret 挂载。最终业务变更仅为这个 Deployment 的 0→1。
- 用户在 B01 摘要后明确批准上述两份清单、Repairer 24 小时短期 Token、独立 Compose bootstrap。用户随后确认本人在网页对提案 `fdfed72e…` 点击了“批准扩容到 1”。Codex 没有点击 Approve、构造 approve Resume、直接调用 scale=1 或运行 `kubectl scale`。
- Compose 项目强制为 `kube-triage-phase3b-gateb`，仅占用本机 `12027/13001`，与固定默认项目 `kube-triage-agent` 及 `ragflow-lab` 隔离。其 API 实际指向 `http://k8s-mcp:8080/mcp` 和 `http://repair-mcp:8080/mcp`，`REPAIR_SIMULATED=false`。`mock-mcp` 因 `api.depends_on` 启动，实际 Reader 调用仍来自 Real MCP。

## B01–B08 矩阵

| Gate | 状态 | 实际证据及边界 |
| --- | --- | --- |
| B01 | **PASS** | SSH 主机/Context/API Server/三节点、Namespace 标签及同名对象不存在均经真实只读查询；稳定栈 6 个及 `ragflow-lab` 5 个容器 ID 预先记录；端口空闲。 |
| B02 | **PASS** | 经单独授权，仅应用两份清单。新 Deployment UID `5c908332…`，项目标签、Selector、Pod Template 与镜像匹配，创建后 `spec.replicas=0`。生成本 worktree 0700 `.local` 中 0600 单 Context Repairer kubeconfig，CA/TLS 校验开启；未复制管理员 kubeconfig。 |
| B03 | **PASS** | 实际 Repairer kubeconfig 的 3 个 allow：目标 `deployments/scale get,update`、目标 `deployments get`；6 个 deny：其它 Deployment scale、Pod 删除、Secret 读取、跨 Namespace scale、普通 Deployment 更新、Pod 创建。Reader scale update 亦为 deny。总计 10/10；仅执行 `auth can-i`，没有为测试拒绝而发写请求。本机 kubectl 使用 `deployments.apps/NAME --subresource=scale` 语法。 |
| B04 | **PASS（修复后）** | 上游镜像为 `v0.0.67`。API 运行态 Reader `tools/list` 恰好四个：`events_list,pods_get,pods_list_in_namespace,pods_log`；Repair MCP 恰好 `resources_scale`。真实 Reader 列出 `triage-sample`；不带 `scale` 的 Repair GET 与固定 Deployment HTTPS GET 均回报相同 UID、0 副本。最初发现零值省略解析 Bug，见下文；修复源码以只读 bind mount 注入本轮 API 后复测通过。 |
| B05 | **PASS** | 独立 Thread `a76f4c62…` 的 proposal `b5cfc909…` 在 SSE/State/Checkpoint 一致，`simulated=false`、0→1。仅发送结构化 `reject`，State 为 `rejected`、`repair_result` 为空；该阶段审计 `repair_decision=1`、`repair_scale_call=0`，真实 Scale 仍为 0。网页打开及刷新后保留拒绝消息。另一个网页预检 Thread 显示真实写入提示及准确提案。 |
| B06 | **FAIL（流程偏差）** | 网页 Thread `90f73e14…` 的 proposal `fdfed72e…` 经用户本人点击 Approve；同一 Thread 审计出现一次 `repair_decision=approve`、一次 `repair_scale_call(outcome=response_received)`，随后 Scale 0→1。但此 Thread 和 `/repair-demo` 是 Codex 为 B05 网页检查创建/输入的，未遵循“由用户本人新建 Thread 并输入命令”的独立 B06 步骤。不能为凑齐 PASS 再重做真实写入。 |
| B07 | **PASS（分层验证）** | 同一 UID 的 Scale/Deployment `spec.replicas=1`；随后只读查询 `readyReplicas=1`，目标 Pod 在 `k8s-node02` 为 Running、`1/1 Ready`。Graph 写后当时报告 `Pod Ready 未知`，原因是 Reader YAML 序列解析 Bug；修复后在关闭写开关的 API 中只读 Reader 回查为 `ready`。0→1 不代表 CrashLoop/OOM 根因修复。 |
| B08 | **PASS（已执行范围）** | Approve Thread 的 State 为 `finished`、History 有 5 个 checkpoint，网页在 API 重建后刷新仍显示同一结果，无待审批卡。先停止 Repair MCP/API，后以 `REPAIR_ENABLED=false` 重建 API 并在容器内核实，再精确清理本轮 Compose。稳定栈与 `ragflow-lab` 全部 11 个容器 ID/健康状态未变。未在写调用中途故意重启，未验证真实 LLM。 |

## 同一 Thread 的实际轨迹

1. `/repair-demo` 经 `_route → repair_prepare`；固定 Deployment HTTPS GET 与 `resources_scale` 只读 GET 证实 UID `5c908332…`、0 副本。Graph 生成 proposal `fdfed72e…`，`repair_approval` 的 `interrupt()` 挂起，网页卡展示 `kube-triage-demo/Deployment/triage-repair-demo：0→1` 及真实写入提示。
2. 用户确认本人在网页点击 Approve。审计于北京时间约 13:49:00 记录 `repair_decision=approve`，同一 run 随后记录一次 `repair_scale_call(target_replicas=1,outcome=response_received)`；约 13:49:01 记录 `repair_result(write_attempted=true)`。该审计只证明本应用观察到一次调用；集群层面不能承诺 exactly-once 或排除外部并发写入。
3. State/History 回查：`repair_status=finished`、`write_response_received=true`、`observed_replicas=1`、`simulated=false`。原结果分类为“写请求已回执且 scale=1；Pod Ready 未知”。只读集群回查分别证实 Deployment Desired=1、Ready=1、目标 Pod Ready=True。

## 发现的问题与最小修复

1. **零副本 Scale 解析**：真实 `v0.0.67` 的 `resources_scale` 返回 `spec: {}`、`status.replicas: 0`；Kubernetes YAML 省略零值。原 `parse_scale()` 将缺失 `spec.replicas` 当成坏响应，导致 B04 首次失败。现仅在 `spec` 为空且 `status.replicas` 明确为 0 时按 0 解析；其它缺失或异常值仍拒绝。新增真实响应形状回归测试。
2. **Pod Ready 解析**：真实 Reader `pods_list_in_namespace` 返回顶层 YAML 序列，原代码只接受 `items`/`pods` 包装对象，导致写后 Ready 误报 unknown。现接受序列和原包装格式，新增 YAML 序列回归测试，并以真实 Reader 只读复测 `ready`。
3. **Docker Desktop 空间**：第一次独立 Postgres 初始化及 Redis AOF 写入报告 `No space left on device`，虽然 macOS Host 仍有约 248 GiB 空间。第一次 Reject 的 HTTP/SSE 因 Redis AOF 报错返回 500，State 已为 rejected；该次未当作完整通过，改用新 Thread 重做。临时 Compose override 将 Postgres/Redis 数据分别 bind 到本 worktree `.local/gateb-postgres`、`.local/gateb-redis`；未清理其它项目或执行全局 prune。修复后的 `repair.py` 亦只读挂载到独立 API，避免重建镜像继续占用 Docker 存储。上述 override 仅为本次验收，不是仓库默认配置。

上游 [v0.0.67 Schema](https://github.com/containers/kubernetes-mcp-server/blob/v0.0.67/pkg/toolsets/core/resources.go#L186-L230) 的 `resources_scale` 参数为 `apiVersion/kind/name/namespace/scale?`，声明 `get/update`；[实现](https://github.com/containers/kubernetes-mcp-server/blob/v0.0.67/pkg/kubernetes/resources.go#L82-L120) 对 `/scale` 先 GET，给出 `scale` 时再 UPDATE。运行态工具集合与这一版本相符。

## 回归、安全与清理

- `uv run --frozen ruff check src tests` PASS；`uv run --frozen pytest -q` **67 passed**。Compose `config --quiet` PASS；独立 Docker 构建中的 Web `pnpm build` PASS；本轮未另行运行本地 Web lint、真实 LLM 或全套 Mock 验收脚本。旧 Gate A 的 65 项记录仍见 [phase3b-validation.md](phase3b-validation.md)。
- Repairer Role 只允许特定 `triage-repair-demo` 的 `deployments/scale get,update` 与 `deployments get`；Reader 保持四个读工具，LLM 只绑定 Reader。敏感 Token、kubeconfig、`.env` 全文及 Pod 日志均未写入报告。用户网页点击发生后，没有自动重试、回滚或第二次 scale。
- 本轮独立 API 已确认 `REPAIR_ENABLED=false`，Repair MCP 已停止。`docker compose -p kube-triage-phase3b-gateb down` 后，按标签精确删除本轮两个具名卷；本轮容器、网络、卷为空。删除本 worktree 的 Repairer/Reader kubeconfig 副本、env、浏览器快照及两份临时 bind 数据目录；主工作树 Reader 凭据未变。文件删除不使已签发 Token 在集群侧立即失效，24 小时请求期满前如需提前撤权，必须另行授权并验证。
- 集群保留 `Deployment/triage-repair-demo`（UID `5c908332…`、Desired/Ready=1）及 `kube-triage-repairer` SA/Role/RoleBinding；未删除、未缩回 0。后续清理需要单独授权。稳定项目及 `ragflow-lab` 容器 ID 与 B01 预检完全相同。

严格 Gate B 未全通过的唯一流程项是 B06 的 Thread 创建/命令输入主体。真实受控写入、人工网页点击、单次应用审计和 Pod Ready 均已有证据；这些事实不替代缺失的指定操作步骤，也不证明全局 exactly-once。
