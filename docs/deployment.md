# 本地部署与数据维护

前提：Docker Compose、Python 3（生成 `.env` 与端口预检）。执行 `./scripts/start.sh`，随后 `make check`。查看服务：`make ps`；日志：`make logs`；停止并保留数据：`make down`。API 地址 `http://localhost:12026`，Web 地址 `http://localhost:13000`。`.env` 包含独立 `POSTGRES_USER`、`POSTGRES_DB`、随机密码、宿主机端口和浏览器 URL，绝不能入 Git。容器内部地址为 `api:2026`、`postgres:5432`、`redis:6379`；浏览器不能使用这些 Docker DNS 名称。

如在 dev01 部署，先另行获得部署指令并重新执行端口和 Compose 项目只读检查。Mac 经 SSH Tunnel 访问时同时转发两端口：

```bash
ssh -N -L 13000:127.0.0.1:13000 -L 12026:127.0.0.1:12026 dev01
```

不要将无认证的 Aegra API 配置成公网入口或自动接 Cloudflare/Nginx。服务器只在该主机回环地址发布端口。

## 备份、恢复和重置

在项目根目录创建不入 Git 的 `backups/`。逻辑备份 PostgreSQL（包含 Aegra Thread、Run、Checkpoint）：

```bash
mkdir -p backups
./scripts/compose.sh exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/kube-triage-agent.dump
./scripts/compose.sh exec -T redis redis-cli SAVE
./scripts/compose.sh cp redis:/data/dump.rdb backups/redis-dump.rdb
```

恢复会覆盖本项目现有数据，应先确认备份文件来源并在一个隔离副本中演练。仅作用于本项目的参考命令如下：

```bash
./scripts/compose.sh stop api web
./scripts/compose.sh exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < backups/kube-triage-agent.dump
./scripts/compose.sh stop redis
docker volume inspect kube-triage-agent_redis_data --format '{{index .Labels "com.docker.compose.project"}}' # 必须输出 kube-triage-agent
./scripts/compose.sh run --rm --no-deps -v "$PWD/backups:/backup:ro" redis sh -c 'rm -rf /data/appendonlydir && cp /backup/redis-dump.rdb /data/dump.rdb'
./scripts/compose.sh up -d --wait
```

Redis RDB 应在 Redis 停止后复制到**本项目**的卷；运行中不要覆盖。正式迁移前应演练恢复，本阶段尚未执行恢复测试。

仅清空本项目数据时运行 `make reset`，脚本展示项目 label 下的卷并要求输入 `DELETE kube-triage-agent`，然后以固定 `-p` 执行 `down --volumes`。请先备份。
