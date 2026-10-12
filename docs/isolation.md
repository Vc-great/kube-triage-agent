# 正式与测试隔离

正式 `infra/compose.yaml` 默认服务：`postgres redis api k8s-mcp web`；`repair-mcp` 只有显式 `repair` profile。没有 Mock 定义、依赖、DNS fallback。测试 `infra/test.compose.yaml` 默认 `postgres redis api mock-mcp web`，`mock-repair-mcp` 需 `repair-mock`；无真实 Kubernetes 服务或凭据挂载。两文件不能叠加。测试环境也使用同一个 Graph，诊断仍需真实模型；无模型时用 pytest FakeModel。

API 正式 URL只允许 `http://k8s-mcp:8080/mcp`；test只允许 `http://mock-mcp:8000/mcp`。显式 `TRIAGE_ENV=test` 是代码保护条件，正式 Compose 无该环境覆写入口。生产 `REPAIR_SIMULATED=true` 拒绝启动与执行；Mock模块的可执行入口拒绝非test。开发者仍可主动修改源码/Compose绕过保护，项目不以这些检查防御恶意操作者。

必须使用独立 Compose项目、空闲回环端口、项目私有网络和专属卷，禁止停止其它项目。`scripts/compose.sh`不再硬编码稳定项目名；无显式 `COMPOSE_PROJECT_NAME` 则失败。无 external卷/network、container_name、Docker socket或特权模式。数据库、Redis、Reader、Repair不发布Host端口；Web/API仅127.0.0.1。凭据 `.local` 0700，文件0600，Git忽略。读取受限凭据前检查身份、Namespace、CA与权限；不输出内容。

当前执行预检与实际运行范围见 [验收记录](real-by-default-review.md)。历史 `docs/phase*` 保留原默认架构、命令及PASS/FAIL/BLOCKED/NOT RUN；它们是阶段记录，当前部署以本文、README、deployment.md为准。Phase3A历史数据及Phase3B B06流程失败不可追溯改写。
