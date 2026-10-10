# 项目隔离

所有 Docker 调用经 `scripts/compose.sh` 强制 `-p kube-triage-agent --env-file .env -f infra/compose.yaml`。仅四个服务：`web`、`api`、`postgres`、`redis`。Compose 自动创建 `kube-triage-agent_private`、`kube-triage-agent_postgres_data`、`kube-triage-agent_redis_data`，并附项目 label。无 `container_name`、外部卷或网络、Docker socket、kubeconfig、特权容器、宿主机项目目录挂载。

PostgreSQL 和 Redis 没有 `ports`，只用项目私有网络的 `postgres:5432`、`redis:6379`。Web 和 API 仅映射 `127.0.0.1`。`make down` 不传 `--volumes`；`make reset` 只在显示本项目卷且人工确认后执行项目限定 `down --volumes`。绝不运行全局 prune 或跨项目停止命令。若端口占用，修改 `.env` 的 `WEB_PORT`/`API_PORT`，同步修改 `NEXT_PUBLIC_API_URL`、`server/aegra.json` 的精确 CORS 来源，再重建 Web；不得停止占用服务。

验收 Docker label 与端口：

```bash
./scripts/compose.sh ps
docker volume ls --filter label=com.docker.compose.project=kube-triage-agent
docker network ls --filter label=com.docker.compose.project=kube-triage-agent
docker ps --filter label=com.docker.compose.project=kube-triage-agent --format '{{.Names}} {{.Ports}}'
```
