# 当前部署与只读验收

dev01 完整应用、IP/端口访问与 Mac 两种开发模式见 [dev01 部署与 Mac 开发](dev01-deployment.md)。下文保留独立本地 Compose 的运行方式。

正常运行需要支持标准 Tool Calling 的真实 OpenAI 兼容模型（`LLM_MODEL`、`LLM_API_KEY`、可选 `LLM_BASE_URL`），以及已经批准、仍有效、仅限 `kube-triage-demo` 的 Reader kubeconfig。不要使用管理员身份、关闭 TLS/CA、自动签发 Token 或修改 RBAC。凭据缺失/过期时 Real E2E 为 BLOCKED；pytest 仍可离线执行。

## 先核对，再启动独立项目

```bash
git fetch origin
docker compose ls
docker ps --format '{{.Names}} {{.Ports}} {{.Labels}}'
docker network ls --format '{{.Name}} {{.Labels}}'
docker volume ls --format '{{.Name}} {{.Labels}}'
lsof -nP -iTCP:12027 -iTCP:13002 -sTCP:LISTEN
./scripts/start.sh --init-only
mkdir -p .local && chmod 700 .local
# 私下放入已获准 Reader kubeconfig；不打印内容。
chmod 600 .local/kubeconfig
export COMPOSE_PROJECT_NAME=kube-triage-real-default-review
./scripts/compose.sh config --quiet
./scripts/start.sh
```

`.env` 默认 API/Web 为 12027/13002（需现场检查占用）；已有 `.env` 不被脚本覆盖或补写。缺模型配置会在 Compose 必填插值阶段失败，非法 URL/模拟模式在容器 CMD 检查阶段失败。API 与 Reader 有明确依赖，无默认 Mock。`LLM_ENABLED=false` 已移除功能，只保留拒绝旧值的兼容提示。不要仅通过服务名、profile 或 `/health` 推断真实链路。

配置优先级：Compose 的 process environment 覆盖 `--env-file` 插值；API 的 environment 指定 `TRIAGE_ENV=production`，模型和 URL 来自插值，客户端没有隐式 URL。测试文件独立固定 Mock URL/test 环境。变更 URL 会清空工具发现缓存；Docker env 变更要重建独立 API，不能只 restart。Web API 地址是构建参数，变更端口须重建 Web；`server/aegra.json` 当前精确允许13000/13001/13002的回环 CORS。

## Real read-only smoke

```bash
python3 scripts/acceptance.py --project kube-triage-real-default-review --env-file .env --api-base http://127.0.0.1:12027
```

脚本先核对 API 容器 project/working_dir/回环端口标签与实际配置，要求 Repair 关闭、模拟关闭、正式 URL；在 API 内发现恰好四工具。随后通过认证创建新 Thread，以中文要求列出现有 Pod，动态选择已有 Pod，读取详情/事件/最多20行日志；不假设故障资源存在。检查 SSE end/无error、Run success、State 无 pending、History 非空、ToolCall/ToolMessage ID计数成对、参数合规、预算、无错误工具、无 static-fixture/mock=true，及最终中文答案。输出仅 ID/工具名/状态，禁止打印全量日志与密钥。脚本失败不能解释为真实通过。

人工 Web 验收另做：本人输入 API Token，查看 Tool Call、ToolMessage、中文总结和历史，刷新后核对同一 Thread。不得由 Codex 替本人批准真实 Repair。自动浏览器检查不等于用户亲验。跨 Namespace/未授权工具拒绝可在独立 API 内对执行层调用，必须在传输前拒绝，不向集群发送禁止操作。

真实 Repair 不在本次范围：保持 `REPAIR_ENABLED=false`，不启动 `repair` profile。后续必须有新的精确授权，使用专用 Repair kubeconfig 与 `infra/repair-api.compose.yaml`，本人审批；禁止把已有 replicas=1 擅自重置为0。

## 测试与停止

`infra/test.compose.yaml` 是独立完整文件，不是覆盖正式文件。合成评测和离线 Gate A 启动命令见 README。两套 Compose 均可用安全占位符纯解析，CI不要求任何真实凭据。`eval_phase3a.py --dry-run` 只校验12项计划，不重现人工评分。

停止时使用与启动完全相同的独立 `-p/--env-file/-f` 前缀加 `down`，不带 `--volumes`。保留独立卷；删除卷、恢复数据库、重置状态须另行确认归属与授权。`scripts/compose.sh` 要求显式 `COMPOSE_PROJECT_NAME`；`scripts/reset.sh` 的标签与确认字串跟随该项目，但本任务不执行。备份与恢复只针对确认的项目，不能复用旧文档的稳定项目硬编码命令。
