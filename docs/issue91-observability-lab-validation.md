# Issue #91 Phase A 实测与 STOP 记录

权威 Gate：[已合并设计 §5](plans/issue-91-observability-fault-lab.md#5-唯一权威验收-gate全部初始-not-run)。本报告仅记录实测，不降低或替代 Gate。

## 当前结论

**Phase A BLOCKED / STOP；Phase B NOT RUN。** 真实 S01 成功，但 Aegra 原生 Langfuse OTLP exporter 两次返回 HTTP 403；Cloud Observations API v2 返回 0 行，不能确认 Trace。没有可交付的真实 Cloud Trace URL，不拼接占位链接。不关闭 #91，不实施 #92。

2026-10-26 核对 Planning PR #93 已合并；实施基线 `origin/main=b259b2ba2efda251e7d657957be6583a2f9c1e35`，独立 AO Worktree、分支 `ao/observability-lab/phase-a`。设计文件顶部仍保留 Proposed 的历史描述，是否合并以 GitHub #93 的 `merged=true` 为准。

## 实现范围

- `scripts/obs_lab.py`：复用 `dev.py` 的权限校验、配置白名单和 `eval_phase3a.py` 的 Agent Protocol/消息协议辅助函数；只运行正式 `agent` Graph 与合成 `memory-web` Mock。
- 每批并发 1、最多 16 Run，Run 超时 30–180 秒，沿用正式 Graph 的 4 次模型决策/6 次工具执行、SDK `max_retries=1`，禁用后台任务重试；失败不自动补跑。
- PG/Redis 使用本机已有镜像、专属容器、临时数据库存储及 `ao.session` 标签。API 使用独立回环端口。Mock 使用 Reader 已允许的端口 8000，已有服务占用时拒绝启动。
- 强制 test、Repair OFF、Memory/History/Evidence/Summary OFF，进程环境不继承 kubeconfig、数据库连接或宿主凭据；不改正式 Graph、Reader、HITL、Checkpoint 或 SSE。
- 唯一 exporter 仍为 Aegra OTel。Cloud 只读查询使用 Japan 同项目 `/projects`、`/v2/observations`，有界窗口和 cursor 分页，唯一 Run/Thread 映射不明确时保留 unknown。没有追加 SDK exporter。
- Cloud 链路校验尚未完成：当前工具 ID 只有 State/History 配对证据；即便找到满足数量/时间/共同祖先的 Span，也仅报告 `timeline_status`，`chain_status` 保持 UNKNOWN，不能冒充 A3 PASS。
- 当前仅交付 Phase A 入口。S04–S08、429 桩、Tool Outcome、#92 的报告恢复/HTML/Scores 均未实现。

## 实际命令与证据

环境：macOS arm64；Python 3.13.14、uv 0.11.21；锁定 Aegra 0.10.8、LangGraph 1.2.14、langchain-openai 1.7.0、OpenAI 3.29.0。依赖从本机缓存安装，无下载。

```sh
cd server
uv sync --frozen --offline --python 3.13
uv run --frozen ruff check src tests ../scripts/obs_lab.py
uv run --frozen pytest -q
uv run --frozen pytest -q tests/test_obs_lab.py
cd ..
git diff --check
```

完整 pytest：**889 passed / 44 skipped**（177.18 秒；新增失败摘要测试前）。新增测试后定向复验：**7 passed**。Skipped 项不算 PASS。Ruff 已通过；未修改前端，不以本地前端测试作为证据。CI 状态由 PR checks 提供，未完成时不能标 PASS。

用户授权配置以 `OBS_LAB_ENV` 显式指定；不复制源文件，不在报告记录内容。源文件为当前用户持有、普通文件、0600。

```sh
# 单次 Smoke：只运行 S01，一批最多 1 Run。
make obs-lab-smoke OBS_LAB_ENV=/absolute/path/to/authorized-private.env

# 仅在 Cloud 403 原因解决、明确恢复后运行 S01–S03 各 2 Run。
make obs-lab-phase-a OBS_LAB_ENV=/absolute/path/to/authorized-private.env

# 自定义有界 Phase A 批次（只接受 S01–S03）。
server/.venv/bin/python scripts/obs_lab.py \
  --env-file /absolute/path/to/authorized-private.env \
  --scenarios S01 S02 S03 --repeats 2 --max-runs 6 \
  --timeout 150 --cloud-wait 120
```

运行需要 Docker、已有 `pgvector/pgvector:0.8.7-pg18-bookworm` 和 `redis:8.4.7-alpine` 镜像及 AO_SESSION_ID；不拉取镜像，不复用稳定 PG/Redis。实验入口明确直连已配置 Provider 和 Langfuse Japan，保留 TLS 校验，不继承 Host proxy。正式 `dev.py` 的代理策略不变。

真实 Smoke 批次：`issue91-20261026-220630-831875`，2026-10-26 14:06 UTC 开始。

| 项目 | 实际结果 |
| --- | --- |
| S01 Thread | `ba944f59-f91e-4646-bb7d-28869150b2da` |
| S01 Run | `f64eeb20-6865-4ef6-8a02-0114b66bf26e` |
| Provider 回显 | `gpt-6-luna`，2 次模型决策；底层 HTTP attempt 未独立观测，不声称只有 2 次请求 |
| Reader | `pods_get`、`pods_log`、`events_list`，共 3 次；Tool Call ID 配对通过 |
| Aegra 终态 | success；SSE 未报告 error；不等同诊断质量 PASS |
| Cloud 项目查询 | 同一组凭据认证查询成功；项目 ID 仅保留私有 manifest |
| Cloud exporter | 启用 Langfuse 与原生自动 instrumentation；2 次 HTTP 403 |
| Cloud v2 | 在有界 120 秒轮询内 0 行，`ingestion_pending`；无真实 Trace ID/URL |
| 隔离/清理 | 本次容器全部清理；原有 `kta-issue78-pg` 未停止；API/Mock 已退出 |
| 凭据审计 | 批次私有文件中模型 API key / Langfuse 公私钥出现次数 0 |

原始合成 State/History/SSE/Cloud rows 与日志位于 Git 忽略的 `.local/observability-lab/<batch_id>/`，目录 0700、文件 0600。不提交原始轨迹、密钥或项目私有信息。

## 逐 Gate 状态

| Gate | 状态 | 证据/缺口 |
| --- | --- | --- |
| A0 | PASS | 最新 main/锁版本核对；独立容器、端口、进程；test/Repair OFF/无 kubeconfig；未触碰 PR #90 |
| A1 | BLOCKED | 仅 S01 真模型+HTTP Thread/Run/SSE 已运行，S02/S03 因 Cloud STOP 未运行 |
| A2 | BLOCKED | Cloud OTLP 403，v2 无 Trace；URL/UI 均无法验证 |
| A3 | BLOCKED | 本地 Tool 配对成功；Cloud 父子/时间线/Tool Call ID 未证实 |
| A4 | NOT RUN | 离线回归通过、凭据审计 0 命中；真实 OTel OFF/网络故障行为对照未运行 |
| A5 | BLOCKED | Smoke 非零退出；CI/完整链路未满足，入口不代表验收通过 |
| B0–B5 | NOT RUN | 未通过 Phase A，禁止进入 Phase B |

## 失败记录与恢复边界

1. 第一轮在模型和容器启动前因硬编码本机 proxy 7890 不监听而返回 URLError，0 Run。一次无凭据 Host 诊断确认直连 Japan HTTPS 正常，测试入口改为明确直连；不更改正式启动器或代理服务。
2. 直连后的唯一真实 Smoke 如上，模型成功但 OTLP 403，Cloud Gate 阻塞。按设计停止，不重新调用模型补 Trace。后续补充启动前失败 manifest 保存、导出错误脱敏摘要、中断和协议异常证据保存，未再次执行真实模型。

需由授权人确认 Langfuse OTLP 403 的写入权限/网络原因，再明确恢复。不能从 REST 读取成功推断 OTLP 写入成功，也不能把 403 简单解释为摄取延迟。恢复时先只读核对既有 Trace，不为补索引重复付费 Run；若需复测 Smoke，仍显式限制 Run 数。

回退：本 PR 仅增加入口/测试/说明与 Make targets，不改变正式服务默认值。退出启动器会关闭其创建的子进程和容器；数据库存储为临时数据，不影响现有卷。失败后先查看本批次资源记录，仅清理本批次标识的残留资源；不得全局 `docker compose down` 或 prune。删除本任务私有输出前由用户决定是否保留反例；回退代码可 revert 本 PR 提交。
