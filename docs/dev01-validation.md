# dev01 部署与 Mac 开发验收记录

日期：2026-10-12（北京时间）。基线 `881a734`；实施分支 `codex/dev01-deployment`。远端目录 `/www/app/kube-triage-agent`，项目 `kube-triage-agent`，Linux amd64。未迁移 Mac 历史数据，远端三个数据卷均首次创建。

| 检查 | 结果 |
| --- | --- |
| Python | Ruff PASS；pytest **97 passed**，含开发 Reader URL 边界、缓存切换、模拟拒绝、进程身份与 CORS 回归 |
| 前端 | Token 地址隔离与旧存储迁移 PASS；lint 0 错误/18 个已有警告；默认 `pnpm build` PASS |
| 配置 | 正式、测试、dev01 Compose 解析；Shell 语法；Python 编译；`git diff --check` PASS |
| 远端镜像 | API/Web 在 dev01 原生 amd64 串行构建 PASS，未更改依赖锁文件 |
| 服务 | Web、API、PostgreSQL、正式 Redis、开发 Redis、Reader 共六个运行；应用及数据库/Redis 健康检查 PASS |
| 正式真实诊断 | PASS：Thread `1af83be2-a8e0-4feb-8925-836b8ff8e7f5`，Run success，四工具全部成功且 ID 配对，SSE end，History 7，中文总结 |
| 开发真实诊断 | PASS：Thread `8e8aef4e-2c95-4000-8917-75b39d985c5a`，Run success，四工具全部成功且 ID 配对，SSE end，History 7，中文总结 |
| 数据隔离 | 两端 API 查询另一环境 Thread 均 HTTP 404；开发数据库账号对正式库 CONNECT=false、开发库 CONNECT=true；两个 Redis 服务各用独立容器/卷 |
| 浏览器 | 远端 Web 与 `dev-web` 实际 API origin 为 `http://192.168.31.110:12026`；`dev` 为 `http://localhost:12026`；旧 apiUrl 查询参数不覆盖模式配置；最终页面 pageErrors=0 |
| 进程管理 | 非自身端口占用时拒绝启动，旧容器不变；仅终止本入口 SSH 隧道后，前后端自动清理，远端 API 仍 HTTP 200；无 Mock 回退 |
| Mac 容器 | 仅原项目四个依赖容器按 ID/项目/目录标签核验后停止；原 PostgreSQL/Redis 卷和其他项目容器保留 |

## 实际遇到的问题与修正

第一次远端构建因 Docker Hub DNS/直连超时失败。Host 检查确认 dev01 已有代理可达，通过 Docker daemon 预取锁定基础镜像后构建成功；没有修改全局代理或其他项目配置。依赖在远端无缓存时按锁文件下载；Mac 依赖全部从已有 uv/pnpm 缓存复用。

Reader 最初因 Linux bind 文件属主与镜像 UID 65532 不匹配而重启；通过 dev01 override 让 Reader 使用私有文件属主 UID/GID 解决。kubeconfig 仍为 0600、只读挂载，CA/TLS 保持开启。仅复用已有受限身份，没有签发 Token 或变更 RBAC。

首次真实诊断选到故障演练 Pod，其日志超时/被 MCP 拒绝，模型耗尽决策预算，严格验收 FAIL。正常 `triage-sample` 详情/日志独立只读调用成功。第二次模型添加不支持的 `fieldSelector`，应用拒绝后模型纠正并生成报告，但“全部调用成功”的严格验收仍 FAIL。最终烟测明确优先选择列表中的正常 Pod，且事件工具只传 namespace 后 PASS。没有放宽策略、延长工具超时或执行 Kubernetes 写入；这不是故障诊断准确率评测，也不代表上述故障 Pod 已修复。

浏览器检查发现原有 localStorage Token 首屏造成 hydration mismatch，以及 SVG `clip-path` 的 React 属性错误。已延后到挂载后读取 Token、改用 `clipPath`，两种开发模式与远端页面复验均无 pageerror。Token 按 origin 保存，模型 Key 不进入前端环境。

## 证据与边界

脱敏诊断证据在 Mac `.local/production-smoke.json`、`.local/development-smoke.json`，远端保留 `.local/production-smoke.json`；不提交完整 SSE、Pod 日志、模型地址和凭据。网页检查使用独立 Playwright 浏览器上下文与本项目新 Token，不读取既有浏览器秘密；没有执行真实 Repair 或 Approve。

远端原有 `cpamp`、`metacubexd`、`ziki` 项目保持运行；Mac `ragflow-lab` 保持运行。未删除卷、prune、恢复覆盖数据库或调整真实 Kubernetes 副本。
