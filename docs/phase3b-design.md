# Phase 3B：固定目标的 HITL 受控恢复

## 当前链路与边界

`graph_id=agent` 保留原来的 LLM ReAct、四个只读 MCP 工具、预算和 `/approve-demo`。`graph.py:_route` 只在文本**精确等于** `/repair-demo` 时进入新分支。自然语言中的建议、模型 Tool Call、Pod 日志和事件均不能进入写入节点。模型的诊断建议是证据与人工建议，不是用户对特定变更的审批授权。

真实路径为 Web → Aegra `X-Api-Key` 认证 → LangGraph `repair_prepare` → checkpoint → `repair_approval` 的 `interrupt()` → 同一 Thread 的 `Command(resume={decision,proposal_id})` → `repair_execute` → 独立 Repair MCP → Kubernetes `deployments/scale` → GET scale、Reader Pod 查询。前端只回传审批决定和 ID；目标从服务端常量构造。Aegra 的认证拦截独立于节点中的业务校验。

状态字段为 `repair_proposal`、`repair_status`、`repair_result`。提案在审批节点之前形成并写入 checkpoint，包含随机 ID、固定目标、目标 UID、0→1、影响和 `source=explicit-user-command`；恢复重放审批节点不会重新生成 ID。审批节点只调用 `interrupt()` 并验证回传，绝不写集群。条件边只对 `approved` 进入执行节点。无效 ID、额外参数、未知决定都落到拒绝终态。

## 工具与身份

- Reader 的 `read_only=true`、四工具白名单和 `kube-triage-reader` RBAC 原样保留，`_llm.bind_tools` 仍只使用 Reader 的 `_allowed_tools()`。
- Repair MCP 是独立 opt-in 容器，v0.0.67 镜像只启用 `resources_scale`，不发布宿主机端口。它使用 `.local/repair-kubeconfig` 中 `kube-triage-repairer` 短期 Token。API 在真实演练的 Compose override 中只读挂载同一凭据，用 HTTPS GET 固定 Deployment 来检查标签与 UID；不提供通用 API 适配器，也不挂管理员凭据。
- Role 在 `kube-triage-demo` 中仅允许 `resourceNames=[triage-repair-demo]` 的 `deployments/scale get/update`，以及同名 `deployments get` 以检查归属。没有 `patch/create/delete` 或普通 Deployment 更新。`resourceNames` 限制名字，业务预检另外核对 namespace、Kind、项目标签、Pod 模板和 UID。
- [上游 v0.0.67 工具定义](https://github.com/containers/kubernetes-mcp-server/blob/v0.0.67/pkg/toolsets/core/resources.go#L186-L230) 声明 `resources_scale` 需要 `get/update`；[对应实现](https://github.com/containers/kubernetes-mcp-server/blob/v0.0.67/pkg/kubernetes/resources.go#L82-L120) 先 GET `/scale` 再 UPDATE `/scale`，并未使用 PATCH。Kubernetes 的 [Deployment Scale 转换](https://github.com/kubernetes/kubernetes/blob/v1.31.0/pkg/registry/apps/deployment/storage/storage.go#L339-L361) 不复制标签，因此单靠 scale 响应不能验证归属。

## 写前与写后

`repair_prepare` 必须先读到本项目固定 Deployment 和副本 0。批准后的 `repair_execute` 再读 Deployment 与 scale、核对 UID、标签、模板和副本。已为 1 时不重复写；其它值或解析/权限/连接错误都停止。写调用有限时，且没有自动重试。若 UPDATE 已生效但回执丢失，回查可能读到 1；结果仍标记“写结果未知/失败”，不宣称本请求唯一造成了状态变化。

写后再次调用不带 `scale` 的 `resources_scale`，核对 `.spec.replicas`，并尝试用 Reader 查询 Pod Ready。三个概念单独呈现：写请求回执、控制面期望副本、Pod Ready。0→1 是控制面演练，不能证明 CrashLoop、OOM 或镜像拉取问题已修好。离线模式使用独立 `mock-repair-mcp`，提案与结果明确 `simulated=true`。

Checkpoint 重放或重复 Resume 后，执行节点再次读到 1 可避免重复写。GET 与 UPDATE 之间仍有并发竞态；两个独立审批可能都读到 0，无法提供 exactly-once。Kubernetes UPDATE 携带 GET 到的 `resourceVersion`，冲突时服务器可拒绝，但本项目不依赖它消除全部竞态。没有分布式锁，也不自动回滚或缩回 0。

## 真实集群 Gate

只有用户另行明确核实 `ssh k8s-m` 的集群、两份清单、短期 Token 创建及网页批准 0→1 后，才可进入 Gate B。若已有同名 Deployment 缺标签或内容不同，停止；不得接管或覆盖。此文档与代码提交本身不授权真实写入。
