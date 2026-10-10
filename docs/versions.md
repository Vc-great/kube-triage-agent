# 锁定版本与来源

| 组件 | 固定版本或来源 | 许可证 / 说明 |
|---|---|---|
| Agent Chat UI | `langchain-ai/agent-chat-ui` commit `28cfb43a62b7179ed4065dd761e16ece8c29d983` | MIT，`apps/web/LICENSE` |
| Aegra CLI/API | PyPI `aegra-cli==0.10.8`，传递依赖 `aegra-api==0.10.8`，详见 `server/uv.lock` | Apache-2.0 |
| LangGraph Python / SDK | `langgraph==1.2.14`、`langgraph-sdk==0.4.6`，见 `server/uv.lock` | MIT；由 uv 锁定 |
| Next.js / React / LangGraph SDK JS | `next==16.3.8`、`react==19.3.0`、`@langchain/langgraph-sdk==1.12.0`，见 `apps/web/pnpm-lock.yaml` | 上游许可证随依赖分发 |
| PostgreSQL + pgvector | `pgvector/pgvector:0.8.7-pg18-bookworm` | PostgreSQL License；PostgreSQL 18 数据卷挂 `/var/lib/postgresql` |
| Redis | `redis:8.4.7-alpine` | Redis 8 三选一许可证（AGPLv3、RSALv2、SSPLv1），详见上游许可证 |
| Python | `python:3.13.14-slim-bookworm` | PSF |
| uv | `ghcr.io/astral-sh/uv:0.11.21` | MIT / Apache-2.0 |
| Node | `node:24.15.0-bookworm` | MIT / Node.js 组件许可证 |
| pnpm | `10.5.1`，上游 `packageManager` 字段 | MIT |

来源：[Aegra 安装](https://github.com/aegra/aegra/blob/main/docs/installation.mdx)、[Aegra 配置](https://github.com/aegra/aegra/blob/main/docs/reference/configuration.mdx)、[Aegra Worker](https://github.com/aegra/aegra/blob/main/docs/guides/worker-architecture.mdx)、[Agent Chat UI](https://github.com/langchain-ai/agent-chat-ui)、[pgvector](https://github.com/pgvector/pgvector)、[Redis 官方镜像](https://hub.docker.com/_/redis)、[PostgreSQL 官方镜像](https://hub.docker.com/_/postgres)。上游核对日期：2026-10-10。重建时仍应核对 tag 是否存在，并记录镜像 digest；当前未将多架构 digest 固定在 Compose。
