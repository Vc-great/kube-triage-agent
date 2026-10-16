# dev01 部署与 Mac 开发

远端目录 `/www/app/kube-triage-agent`，Compose 项目 `kube-triage-agent`。正式环境和本机 `make dev` 使用真实模型与受限 Reader MCP；`make dev` 另经独立 Repair MCP 开启受控真实 Repair。远端正式 API 仍关闭 Repair，本机 Mock 场景仍使用真实模型且关闭 Repair。

实际检查与失败修正记录见 [验收记录](dev01-validation.md)。

| 模式 | Web | API | 数据 |
| --- | --- | --- | --- |
| 远端完整应用 | `http://192.168.31.110:13000` | `http://192.168.31.110:12026` | 正式库、正式 Redis |
| `make dev-web` | `http://localhost:13000` | dev01 API | 正式数据 |
| `make dev` | `http://localhost:13000` | `http://localhost:12026` | 真实 Reader + 受控 Repair；Memory 读写；Window + Summary |
| `make dev-mock` | `http://localhost:13000` | `http://localhost:12026` | 本机 Mock；Memory/Context 关闭 |
| `make dev-memory-write` | `http://localhost:13000` | `http://localhost:12026` | 本机 Mock；Memory 只写 |
| `make dev-memory-read` | `http://localhost:13000` | `http://localhost:12026` | 本机 Mock；Memory 只读 |
| `make dev-memory` | `http://localhost:13000` | `http://localhost:12026` | 本机 Mock；Memory 读写 |
| `make dev-mock-window` | `http://localhost:13000` | `http://localhost:12026` | 本机 Mock；Context Window |
| `make dev-mock-summary` | `http://localhost:13000` | `http://localhost:12026` | 本机 Mock；Context Window + Summary |

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

`.local/dev.env` 按 `.env.development.example` 配置，权限必须为 0600。只保存 `POSTGRES_PASSWORD`、`DEMO_API_TOKEN`、`LLM_MODEL`、`LLM_BASE_URL`、`LLM_API_KEY`、独立的 `INCIDENT_MEMORY_PROVENANCE_SECRET`；可选 `DEV_SSH_HOST` 和 `DEV_REMOTE_API_URL`。不要在此设置 `TRIAGE_ENV`、Reader URL、Memory/Context/Repair 开关、数据库身份或端口。重复键和其他键会被拒绝。开发入口固定 `kube_triage_agent_dev` 账号/数据库与开发 Redis；前端进程不接收数据库密码或模型 Key。`dev-web` 创建的会话属于正式应用，其余本地 API 场景共用开发库。

首次准备 Runtime 时先检查 Host 已有工具和缓存，再在项目内执行：

```bash
cd server
uv sync --frozen --offline --python 3.13
cd ../apps/web
pnpm install --offline --frozen-lockfile
cd ../..
```

## Mac 本地人工场景验收

所有 Mock 命令使用本机回环 Mock MCP（`127.0.0.1:8000/mcp`）与同一套 `memory-web` 合成 Pod 数据。SSH 只转发开发数据库和 Redis，不连接真实 Reader。`make dev` 还转发真实 Reader `18080` 与受限 Repair MCP `18081`，开启 Memory 读写、Window、Summary（估算预算 6500）及真实 Repair。所有模式共用端口与 supervisor，切换前先 `make dev-stop`；仓库根目录 `.env` 不被此启动入口读取。

Memory HMAC 密钥由准备脚本生成；既有私有文件需自行保留一份独立的 32–256 字符 ASCII 密钥，不能与 `DEMO_API_TOKEN` 相同。启动命令设置全部 Memory 开关，不需要修改私有文件。Window 与 Summary 模式使用相同的 6500 估算预算；短对话未必触发摘要，需在同一 Thread 连续多轮提问并核对 State/日志。Mock 与真实 Reader 共用现有开发库，历史合成案例会留在该库；使用新 Thread 记录人工测试结果。

### `make dev` 的真实 Repair 前置条件

先只读核对 `kube-triage-demo/Deployment/triage-repair-demo`、专用 Repairer SA/Role/RoleBinding、目标 UID/归属标签和当前副本数；清单与权限边界见 [Gate B 手册](phase3b-gateb-runbook.md)。缺少对象时，按该手册单独准备，`make dev` 不会自动创建或改变集群资源。目标已有 1 副本可以启动；此时 `/repair-demo` 不产生 0→1 审批提案。只有用户本人在网页审阅并批准有效提案时才可能发生真实写入。

本机 `.local/repair-kubeconfig` 与 dev01 `.local/repair-kubeconfig` 必须是有效的、0600 的单 Context 受限 Repairer 凭据，不能使用管理员身份。需要刷新时，按手册执行 `scripts/refresh-kubeconfig.py --ssh-host k8s-m --account kube-triage-repairer --confirm k8s-m/kube-triage-demo/kube-triage-repairer`，然后经已确认的 SSH 主机安全放置到 dev01；不要输出文件内容。dev01 文件属主须匹配 `.env` 的 `READER_UID/READER_GID`。在 dev01 检查现有镜像/服务能力、Compose 归属和 `18081` 端口后，仅启动独立服务：

```bash
cd /www/app/kube-triage-agent
./scripts/dev01-compose.sh --profile repair config --quiet
./scripts/dev01-compose.sh --profile repair up -d --wait repair-mcp
```

`make dev` 启动预检会读取真实 Pod 列表、验证 Reader 四个只读工具，检查本机 Repairer 凭据与 RBAC，再通过 Repair MCP 只读查询固定 Deployment/Scale。任一项失败则终止启动，具体失败组件见私有 `.local/dev/preflight.log`；不切换到 Mock 或关闭 Repair 继续运行。

```bash
chmod 600 .local/dev.env
make dev-stop
make dev-mock
make dev-status
lsof -nP -iTCP:8000 -iTCP:12026 -iTCP:13000 -sTCP:LISTEN
```

人工测试顺序：`make dev` 验证真实 Reader、Memory 保存/召回、Context 多轮摘要和 Repair 审批拒绝路径；停止后 `make dev-mock` 分别诊断四类合成 Pod；再用 `make dev-memory-write` 保存案例，停止并以 `make dev-memory-read` 启动，在新 Thread 核对召回；`make dev-memory` 验证保存和撤销。最后分别用 `make dev-mock-window` 与 `make dev-mock-summary` 对同类多轮对话检查裁剪、摘要与安全回退。每次启动后执行 `make dev-status` 核对 Reader、Memory、Context、Repair 摘要。Memory 与 Repair 审批必须由你在浏览器亲自操作，不能只凭卡片消失判定成功。

浏览器打开 `http://localhost:13000`。Web 默认 API 是 `http://localhost:12026`；
`NEXT_PUBLIC_API_URL` 优先于 URL 中的 `apiUrl` 参数。Web 按 API 地址分别存储
Demo Key，请使用 `.local/dev.env` 对应的 Key。Memory 场景先诊断 `kube-triage-demo` 中的
`imagepull-pod`，确认有成功的 `pods_get`，紧接着在同一会话发送精确命令
`/remember-incident`。审批卡中的 UID 来自独立合成 fixture。批准、拒绝和撤销
必须由你在浏览器中亲自操作；撤销命令是 `/forget-incident <memory_id>`。

若启动预检失败，查看 `.local/dev/{mock,preflight,api,supervisor}.log`；
先确认 `8000` 上只有本次 Mock、`12026` 上只有本次 Aegra。不要把包含密钥的日志
贴入公开渠道。

## 首次部署与更新

```bash
python3 scripts/prepare-dev01.py --source-env /path/to/approved/model.env
./scripts/deploy-dev01.sh
```

准备脚本生成 `.local/dev01.env`、`.local/dev.env`（0600），随机生成独立密码、Token 和本机 Memory HMAC 密钥，只复用源配置中的模型设置，不覆盖已有文件。同步脚本排除私密文件、依赖和缓存，不删除远端文件。首次需单独通过 SSH 将 `.local/dev01.env` 放为远端 `.env`，将已授权且有效的 Reader kubeconfig 放为远端 `.local/kubeconfig`；文件 0600、目录 0700。拒绝覆盖既有私有配置，不发送管理员 kubeconfig，不自动签发凭据。

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

镜像在 Linux amd64 上串行构建。Web/API 绑定 `192.168.31.110:13000/12026`，Web 构建使用远端 API 地址。PostgreSQL `15432`、开发 Redis `16379`、Reader `18080` 与独立 Repair MCP `18081` 仅绑定远端回环地址，经 SSH 转发到 Mac 相同端口；正式 Redis 不发布端口。

空 PostgreSQL 卷首次初始化创建开发账号和开发库，开发账号无权连接正式库。两套 API 各自迁移自己的数据库。旧卷不会再次执行初始化；后续新增开发库应显式创建，不能通过删卷触发初始化。改数据库密码需同步更新数据库账号，不能只改环境文件。

Linux Reader 和 Repair MCP 容器使用 `.env` 中的 `READER_UID/READER_GID`，必须与各自私有 kubeconfig 文件属主一致（当前为 dev01 的 `dev` 用户）。这样保持两个文件为 0600 和只读挂载，不需要扩大文件读取权限。Repair MCP 仅随 `--profile repair` 启动；远端正式 API 的 `REPAIR_ENABLED=false` 不随之改变。

源码同步不会自动更新运行镜像；重建并 `up` 对应服务才更新。Web API URL 是构建配置，改变时须重建 Web。CORS 允许远端网页和 Mac 回环网页；健康检查不代替真实链路验收。

## 验收与回退

本地联调就绪后：

```bash
server/.venv/bin/python scripts/acceptance_dev01.py --target development --env-file .local/dev.env
```

验收会创建真实只读诊断会话，检查认证、CORS、四工具发现、中文诊断、SSE、State/History 和 Tool Call ID 配对，不执行 Repair。脱敏证据保存在 `.local/{production,development}-smoke.json`，不输出 Pod 日志和密钥。

远端停止并保留卷：`ssh dev01 'cd /www/app/kube-triage-agent && ./scripts/dev01-compose.sh down'`。本地 `make dev-stop` 不操作远端 Docker。

Mac 旧项目容器按归属停止，历史数据不迁移，原数据库和 Redis 卷保留。回退先 `make dev-stop` 释放隧道端口，再按原容器 ID 启动旧依赖。保留旧 Compose 配置、卷和原 `.env`；不执行 `down --volumes`、`system prune` 或覆盖恢复。其他 Docker 项目不变。
