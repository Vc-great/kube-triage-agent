# kube-triage-agent — Phase 1A Demo

单用户本机演示：Aegra 鉴权、LangGraph 确定性路由、跨容器 Mock MCP、审计和 CI。Pod/Event/Log 全是静态 fixture；没有真实 Kubernetes、LLM、自动修复或部署操作。

```bash
make up       # 首次生成本项目私有 .env；构建五个 Compose 服务
make ps       # 查看本项目容器
make check    # Compose 静态校验 + API/SSE/审批/持久化验收
make down     # 停止，仅本项目，保留数据库卷
```

打开 [Web](http://localhost:13000)。从本项目 `.env` 的 `DEMO_API_TOKEN` 取值，填入页面的 **Demo API Key**；请勿把值复制到截图、Issue 或聊天。输入 `pods demo`、`events demo crashloop-pod`、`logs demo crashloop-pod`；`pods default` 会被拒绝。`/approve-demo` 可测试模拟审批。API 默认是 `127.0.0.1:12026`，MCP/PostgreSQL/Redis 不发布宿主机端口。

开发检查：

```bash
cd server && uv sync --frozen --python 3.13 && uv run --frozen ruff check src tests && uv run --frozen pytest -q
cd apps/web && pnpm install --frozen-lockfile && pnpm lint && pnpm build
```

只允许个人本机或可信 SSH Tunnel 访问。固定 Token 存于本项目 `.env` 和浏览器 localStorage，后者可被同源脚本读取；这不是公网或生产级身份方案。绝不提交 `.env`。`make reset` 需要人工输入确认语才会删除本项目卷，通常无需执行。若浏览器 Key 错误，受保护的 Assistant 查询会提示重输。

设计和学习资料：[Phase 1A 设计](docs/phase1a-design.md)、[验收证据](docs/phase1a-validation.md)、[面试问答](docs/phase1a-interview.md)、[隔离说明](docs/isolation.md)。Phase 0 的实测记录保留在 [Phase 0 验证](docs/phase0-validation.md)。
