# kube-triage-agent — Phase 0

本仓库目前仅是 **本地隔离演示**。Graph 无 LLM Key、无 Kubernetes/MCP 连接、无集群写操作。`AUTH_TYPE=noop` 表示任何可访问 API 的人都能读写 Thread/Run；只允许本机或可信 SSH Tunnel 使用，严禁公网暴露。

## 一键启动

```bash
./scripts/start.sh
```

脚本首次生成不入 Git 的 `.env`（独立随机数据库密码），只读检查端口，静态校验 Compose，再以固定项目名启动。打开 [Web](http://localhost:13000)；[API health](http://localhost:12026/health)。在聊天里输入 `status` 可见 `get_demo_cluster_status` 模拟工具调用；输入 `/approve-demo` 可进入模拟审批。默认仅监听宿主机 `127.0.0.1`。

固定 Compose 调用形式：

```bash
docker compose -p kube-triage-agent --env-file .env -f infra/compose.yaml ps
```

`make ps`、`make logs`、`make check`、`make down` 调用相同的项目限定脚本。`make down` 保留数据。`make reset` 会列出本项目卷并要求输入完整确认语后才删除本项目卷。不要将 `.env` 或 `backups/` 提交 Git。

## 实现边界

- `apps/web/` 从 [Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui) commit `28cfb43a62b7179ed4065dd761e16ece8c29d983` 导入，保留上游 [MIT LICENSE](apps/web/LICENSE)、pnpm 锁文件与上游 README。更新时比较该 commit 与新版本并移植本项目差异；不混用 npm lockfile。
- `server/` 使用 PyPI `aegra-cli==0.10.8`（包括 `aegra-api`），不复制 Aegra 源码。Aegra 采用 Apache-2.0。Graph 仅有模拟响应、模拟工具和 `interrupt()` 审批。更新时改版本、重生成 `uv.lock` 并重跑验收。
- `infra/compose.yaml` 是唯一正式部署入口；数据库和 Redis 是本项目独立容器和 Compose 命名卷。后续 MCP 接口位置为 `server/src/kube_triage/` 内新增只读 MCP adapter，在独立鉴权和审批策略完成前不接真实集群。

详细架构、环境变量、隔离、备份和执行证据见 [docs/architecture.md](docs/architecture.md)、[docs/deployment.md](docs/deployment.md)、[docs/isolation.md](docs/isolation.md)、[docs/versions.md](docs/versions.md)、[docs/phase0-validation.md](docs/phase0-validation.md)。
