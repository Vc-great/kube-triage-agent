# dev01 部署与 Mac 开发

远端目录 `/www/app/kube-triage-agent`，Compose 项目 `kube-triage-agent`。正式与开发环境均使用真实模型和共享的受限 Reader MCP，Repair 关闭。

实际检查与失败修正记录见 [验收记录](dev01-validation.md)。

| 模式 | Web | API | 数据 |
| --- | --- | --- | --- |
| 远端完整应用 | `http://192.168.31.110:13000` | `http://192.168.31.110:12026` | 正式库、正式 Redis |
| `make dev-web` | `http://localhost:13000` | dev01 API | 正式数据 |
| `make dev` | `http://localhost:13000` | `http://localhost:12026` | 远端开发库、独立开发 Redis |

## Mac 日常命令

在已配置本项目的 Mac checkout 根目录执行：

```bash
make dev-web
make dev-stop  # 切换模式前停止当前开发服务
make dev
make dev-status
make dev-stop
```

服务在后台运行；日志位于 `.local/dev/{web,api,tunnel,supervisor}.log`，权限为 0600。停止前校验 supervisor 路径和随机身份，只清理自己启动的进程，不按端口盲目杀进程。遇到其他程序占用端口会报错；隧道退出时停止本次开发进程并报告错误，不切到 Mock。远端应用不受开发入口启停影响。

使用命令打印的新 URL，避免沿用旧 `apiUrl` 查询参数。`NEXT_PUBLIC_API_URL` 优先于查询参数。网页 API Token 根据目标 API 地址隔离：远端 Token 私下查看 `.local/dev01.env`，开发 Token 私下查看 `.local/dev.env` 的 `DEMO_API_TOKEN`，再在网页输入。不要把 Token 放进 URL、截图或 Git。

`.local/dev.env` 按 `.env.development.example` 配置，权限必须为 0600。开发入口强制选择 `kube_triage_agent_dev` 账号/数据库、开发 Redis、`TRIAGE_ENV=development`、真实模型、固定 Reader 回环 URL；前端进程不接收数据库密码或模型 Key。`dev-web` 创建的会话属于正式应用，`dev` 会话属于开发库。

首次准备 Runtime 时先检查 Host 已有工具和缓存，再在项目内执行：

```bash
cd server
uv sync --frozen --offline --python 3.13
cd ../apps/web
pnpm install --offline --frozen-lockfile
cd ../..
```

## 首次部署与更新

```bash
python3 scripts/prepare-dev01.py --source-env /path/to/approved/model.env
./scripts/deploy-dev01.sh
```

准备脚本生成 `.local/dev01.env`、`.local/dev.env`（0600），随机生成独立密码和 Token，只复用源配置中的模型设置，不覆盖已有文件。同步脚本排除私密文件、依赖和缓存，不删除远端文件。首次需单独通过 SSH 将 `.local/dev01.env` 放为远端 `.env`，将已授权且有效的 Reader kubeconfig 放为远端 `.local/kubeconfig`；文件 0600、目录 0700。拒绝覆盖既有私有配置，不发送管理员 kubeconfig，不自动签发凭据。

在 dev01 执行：

```bash
cd /www/app/kube-triage-agent
./scripts/dev01-compose.sh config --quiet
./scripts/dev01-compose.sh build api
./scripts/dev01-compose.sh build web
./scripts/dev01-compose.sh up -d --wait postgres redis redis-dev k8s-mcp api web
./scripts/dev01-compose.sh ps
./scripts/dev01-compose.sh logs -f --tail=100 api
python3 scripts/acceptance_dev01.py --target production --env-file .env
```

镜像在 Linux amd64 上串行构建。Web/API 绑定 `192.168.31.110:13000/12026`，Web 构建使用远端 API 地址。PostgreSQL `15432`、开发 Redis `16379`、Reader `18080` 仅绑定远端回环地址，经 SSH 转发到 Mac 相同端口；正式 Redis 不发布端口。

空 PostgreSQL 卷首次初始化创建开发账号和开发库，开发账号无权连接正式库。两套 API 各自迁移自己的数据库。旧卷不会再次执行初始化；后续新增开发库应显式创建，不能通过删卷触发初始化。改数据库密码需同步更新数据库账号，不能只改环境文件。

Linux Reader 容器使用 `.env` 中的 `READER_UID/READER_GID`，必须与 Reader 私有文件属主一致（当前为 dev01 的 `dev` 用户）。这样保持 kubeconfig 为 0600 和只读挂载，不需要扩大文件读取权限。

源码同步不会自动更新运行镜像；重建并 `up` 对应服务才更新。Web API URL 是构建配置，改变时须重建 Web。CORS 允许远端网页和 Mac 回环网页；健康检查不代替真实链路验收。

## 验收与回退

本地联调就绪后：

```bash
server/.venv/bin/python scripts/acceptance_dev01.py --target development --env-file .local/dev.env
```

验收会创建真实只读诊断会话，检查认证、CORS、四工具发现、中文诊断、SSE、State/History 和 Tool Call ID 配对，不执行 Repair。脱敏证据保存在 `.local/{production,development}-smoke.json`，不输出 Pod 日志和密钥。

远端停止并保留卷：`ssh dev01 'cd /www/app/kube-triage-agent && ./scripts/dev01-compose.sh down'`。本地 `make dev-stop` 不操作远端 Docker。

Mac 旧项目容器按归属停止，历史数据不迁移，原数据库和 Redis 卷保留。回退先 `make dev-stop` 释放隧道端口，再按原容器 ID 启动旧依赖。保留旧 Compose 配置、卷和原 `.env`；不执行 `down --volumes`、`system prune` 或覆盖恢复。其他 Docker 项目不变。
