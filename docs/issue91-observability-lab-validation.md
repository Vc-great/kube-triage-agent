# Issue #91 Phase A 验收报告（含历史 STOP）

权威验收仍是 [设计 §5](plans/issue-91-observability-fault-lab.md#5-唯一权威验收-gate全部初始-not-run)，本报告只列实测证据，不更改 Gate。

## 2026-10-27 Phase A 收口：当前状态

**A0–A5 PASS；Phase A READY FOR PHASE B。** 本结论对应本轮已验证的新实现，不表示自动合并或授权实施 Phase B。 本轮只做 Phase A；不实施 S04–S08、#92，不关闭 #91，不自动合并。PR #94 已合并，但其 A3 BLOCKED 不是本轮完成证明。

基线：`origin/main=7b9a908b6dd33fcf33b4fbb9a542334d096f4dde`。独立 Worktree `/private/tmp/kta-issue91-phase-a-closeout`、分支 `ao/observability-lab/phase-a-closeout`。Python 3.13.14、Aegra 0.10.8、LangGraph 1.2.14、OTel 1.45.1，锁文件未改；uv 使用本机缓存，无工具/依赖升级。只读取用户明确授权的私有配置源，忽略已注释的旧组，不复制配置；源文件权限和属主校验保留。

### 根因与最小修复

1. **先只读旧 Trace** `71131804848f292fa6f215d7db86836d`：按真实 ID、扩大至原 Run 前后各 60 秒的限定窗口分页回查，仍只有 8 条（1 Generation、2 Tool、5 Chain），缺根及最终 Generation。旧 State/History 两次模型决策、两次 Reader 与 Tool ID 配对正常。数据仍缺失，不能归因为短延迟、Session 过滤或猜错 Trace。
2. **导出生命周期**：Aegra 0.10.8 lifespan 在 worker drain 后不显式 flush；Uvicorn 0.54.0 的 `capture_signals()` 在清理后重新触发 SIGTERM，不能依赖 Python atexit 排空 BatchSpanProcessor。旧 Runner 收到 Run 成功后立即终止整个 CLI/API 进程组，尾部 Span 会留在批队列。新增 `scripts/obs_lab_api.py` 仅包裹测试 API 的原生 lifespan，在 native worker drain 后对**同一个原生 TracerProvider**调用 10 秒有界 `force_flush`。无第二套 exporter、无重复 Generation、无正式 Graph/SDK/协议改动。新 Run 已实际出现完整根及尾部 Generation，验证此修复路径。
3. **验收逻辑**：旧 Runner 仅以 Trace 存在退出0。现在区分 `trace_verified` / `chain_verified`；必须有完整唯一根、无缺失/循环的祖先链、父时间覆盖子时间，所有模型调用/工具数量与 State 相符。每个调用逐项核对 Cloud Generation 输出 ID/名称/参数、Tool Span 名称/参数/时间、紧接的后续 Generation 输入 ToolMessage ID，并核对本地 State/History 模型序列与工具执行回执。任一项缺失就 BLOCKED，异步摄取只读等待有界，不补跑模型。
4. **观测表示兼容**：原生单参数 Reader（events_list/pods_list_in_namespace）Span input 实际可能是 Namespace 标量。仅按既有单参数 Schema 规范化；不猜测多参数工具、不放宽 Namespace/Reader 参数。首个新 S01 因这一兼容问题非零退出，原记录保留；修正后只用同份已保存 Cloud 数据复验完整链，通过后才用预留预算复验最终 Smoke。
5. **复用冻结数据**：S01=`sample-e`（Running/Ready）、S02=`sample-a`（APP_CONFIG_PATH 缺失）、S03=`sample-c`（镜像 NotFound），复用 #12 的 `issue12-blind-v1` Fixture 与证据检查。既有 memory-web 仅为旧报告数据，不将其较泛的错误描述冒充上述新案例。无新增 Mock 权限/接口。

### 本轮逐 Gate

| Gate | 状态 | 可核对证据 |
| --- | --- | --- |
| A0 | PASS | 上述 main SHA/独立 Worktree；PG/Redis 专属临时存储与 ao.session 标签、API 回环端口、Mock 固定允许端点；test、Repair OFF、Memory/History/Evidence OFF，无 kubeconfig；原有 kta-issue78-pg 未动 |
| A1 | PASS | S01/S02/S03 均经真实 Aegra Thread/Run/SSE，Provider 回显 gpt-6-luna；每条协议 success、Reader 合法及目标证据满足、State/History 模型序列和ToolID配对通过 |
| A2 | PASS | 下表三个场景均从同一认证项目的 Cloud v2 唯一反查真实 Trace；public=false，链接须有项目权限账号登录；人工 UI 访问 NOT RUN，未伪称手动打开 |
| A3 | PASS | 三个场景均 chain_verified=true；完整根/时间/父链与逐 Tool ID 桥接已核对，具体 ID 见下表；不是由数量猜测 |
| A4 | PASS | 第5 Run OTel OFF、无 exporter；第6 Run 专属回环接收器实际拒绝3批导出，Agent 仍 success；两者目标 Ready 证据、工具协议、State/History配对及诊断完成断言与正常S01一致。文字/调用次数允许真实模型差异，不宣称逐字一致或诊断质量评分。原生 flush 异常不改变执行结果另有确定性测试。源凭据/编码认证串审计0命中；仅合成数据；本次资源已全部清理 |
| A5 | PASS | 最终 make Smoke 实际退出0且完整Cloud链通过；Ruff、37项定向测试通过；代码head `12d8024` 的[6项CI全部通过](https://github.com/Vc-great/kube-triage-agent/actions/runs/40438912755)，Python CI 919 passed/47 skipped，AO原生审查 approved；最终报告更新不改运行代码 |

### 真实 Cloud 链与 Tool ID 证据

Tool Span 本身不一定带直接 Tool Call ID。这里的 ID 证据来自 **Cloud Generation 的结构化工具请求/ToolMessage输入 + Tool Span 名称/规范化参数/所处时间段 + 本地 State/History 配对**。没有把本地结果冒充 Cloud 上直接存在的 Tool ID 字段。所有相关 Span 必须沿实际 parentObservationId 回到各自根，并满足 `request.end ≤ tool.start ≤ tool.end ≤ response.start`。

| 场景 | 实际 Aegra Run ID | Generation/Tool | Cloud 根 | 真实链接 |
| --- | --- | --- | --- | --- |
| S01 | `f2f07909-5603-42da-a89d-5cfb0c2bd164` | 3/3 | `7fea1fe0493c90ab` | [Trace](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/11261c84e536e52bad62a3be836213c7) |
| S02 | `148ddbc8-9e3d-41cf-b4fa-29b72d9562c1` | 2/3 | `9cae04f569187ad1` | [Trace](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/b4b180df4d414eae557fe6217a1207ea) |
| S03 | `cf2fa83d-35fa-4ec9-a7c2-aebefda9fb32` | 2/3 | `74a57b0dcb8f8100` | [Trace](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/0ee9f699494f065937f31e347477d6e7) |

| 场景 | Tool Call ID（State/History和Cloud Generation IO一致） | 请求Generation → Tool Observation → 响应Generation |
| --- | --- | --- |
| S01 | `call_E4EXfKeybSNY6eMl28Sdlodm` | `b78da39f4637b92a` → `b05ee16be0e3aea6` → `4571fbf3aec4c08d` |
| S01 | `call_8fKLVrI5eDBk4Il23Rxb6Xj2` | `4571fbf3aec4c08d` → `8f463b739e1a1215` → `0a5fe3fa2b3d284b` |
| S01 | `call_fGP3U7USdh7ZkdG16iBOAXts` | `4571fbf3aec4c08d` → `d4534153cdb2b28b` → `0a5fe3fa2b3d284b` |
| S02 | `call_Y89BMKq28qFcXfP7l3irfAH8` | `62871faa1a0d2831` → `c8aeb4aab688e706` → `a0ae86eda44549c2` |
| S02 | `call_7qdIb0MVhitNgO2hX1GUeC39` | `62871faa1a0d2831` → `b9189f82c3de40ae` → `a0ae86eda44549c2` |
| S02 | `call_uz2qtJCGXP4WOa2C8otbg30R` | `62871faa1a0d2831` → `fae73702deecb672` → `a0ae86eda44549c2` |
| S03 | `call_RX1F3pRswVhfDCfNI716DGoG` | `ac0e5d6ee98a8369` → `84dfba88e5bcc53e` → `75cb5ae51cf44e7c` |
| S03 | `call_VYhkyKygkl2bhI5Uz2aLmtv7` | `ac0e5d6ee98a8369` → `54ee87d816a1fd7a` → `75cb5ae51cf44e7c` |
| S03 | `call_tTxiARJvZCZegGBOj2laWJoQ` | `ac0e5d6ee98a8369` → `8a309664d2fcb7d6` → `75cb5ae51cf44e7c` |

S01 的实际父链与时间（UTC；各节点的父 ID 均来自 Cloud，而非人工补齐）：

| Observation | 类型 | parentObservationId | startTime → endTime |
| --- | --- | --- | --- |
| `7fea1fe0493c90ab` | CHAIN | `None` | 2026-10-27T02:02:36.301Z → 2026-10-27T02:02:50.422Z |
| `52934e2fbfba0d4c` | CHAIN | `7fea1fe0493c90ab` | 2026-10-27T02:02:36.315Z → 2026-10-27T02:02:39.037Z |
| `b78da39f4637b92a` | GENERATION | `52934e2fbfba0d4c` | 2026-10-27T02:02:36.421Z → 2026-10-27T02:02:39.033Z |
| `c3b59d69816c9010` | CHAIN | `7fea1fe0493c90ab` | 2026-10-27T02:02:39.062Z → 2026-10-27T02:02:39.121Z |
| `b05ee16be0e3aea6` | TOOL | `c3b59d69816c9010` | 2026-10-27T02:02:39.066Z → 2026-10-27T02:02:39.120Z |
| `7e2225f1a1589d8e` | CHAIN | `7fea1fe0493c90ab` | 2026-10-27T02:02:39.130Z → 2026-10-27T02:02:42.640Z |
| `4571fbf3aec4c08d` | GENERATION | `7e2225f1a1589d8e` | 2026-10-27T02:02:39.132Z → 2026-10-27T02:02:42.637Z |
| `fce4f8e2f3d6f65a` | CHAIN | `7fea1fe0493c90ab` | 2026-10-27T02:02:42.651Z → 2026-10-27T02:02:42.734Z |
| `8f463b739e1a1215` | TOOL | `fce4f8e2f3d6f65a` | 2026-10-27T02:02:42.653Z → 2026-10-27T02:02:42.696Z |
| `d4534153cdb2b28b` | TOOL | `fce4f8e2f3d6f65a` | 2026-10-27T02:02:42.697Z → 2026-10-27T02:02:42.733Z |
| `1a38449bfcc20131` | CHAIN | `7fea1fe0493c90ab` | 2026-10-27T02:02:42.749Z → 2026-10-27T02:02:50.396Z |
| `0a5fe3fa2b3d284b` | GENERATION | `1a38449bfcc20131` | 2026-10-27T02:02:42.753Z → 2026-10-27T02:02:50.389Z |

表中包含实际 llm/tools Chain 节点，校验器完整遍历父链；私有完整 Observation JSON 保存在各批次目录，不提交原始 Prompt/ToolMessage。

### 实际调用预算、失败与负测

本轮 **6/6 Agent Run，串行**；共 **17 次模型客户端 HTTP POST、17 次 State 模型决策、19 次 Reader 执行**。17 次模型 HTTP 请求均为日志可见请求；Provider/代理内部调用或费用 UNKNOWN，不按公开价格估计。保留 SDK max_retries=1、单Run 150秒（允许参数30–180秒）、模型4次/工具6次、Cloud120秒；后台Job重试0，无自动补跑。

| 顺序 | 场景/模式 | Run ID | 模型/工具 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | S01/cloud | `94d13bbf-435d-42aa-8bbf-21c2f72e14a0` | 4/3 | 首次解析缺陷：make非零，原manifest BLOCKED保留；同份数据后验链PASS |
| 2 | S01/cloud | `f2f07909-5603-42da-a89d-5cfb0c2bd164` | 3/3 | Cloud链PASS、命令退出0 |
| 3 | S02/cloud | `148ddbc8-9e3d-41cf-b4fa-29b72d9562c1` | 2/3 | Cloud链PASS、命令退出0 |
| 4 | S03/cloud | `cf2fa83d-35fa-4ec9-a7c2-aebefda9fb32` | 2/3 | Cloud链PASS、命令退出0 |
| 5 | S01/off | `f87e1a8e-0c38-4760-9c53-91dff2440803` | 3/4 | A4负测PASS，未尝试Cloud摄取 |
| 6 | S01/failure | `f182b285-0df3-4901-9696-083185a9fee2` | 3/3 | A4负测PASS，未尝试Cloud摄取 |

批次：`issue91-20261027-095729-45e3fb`（首轮失败）、`issue91-20261027-100230-ec4360`（最终Smoke）、`issue91-20261027-100504-cd801e`（S02/S03）、`issue91-20261027-100831-0c5ef6`（OFF）、`issue91-20261027-101134-8824b9`（受控失败）。首次失败包含在6 Run内，不删除/改写其原manifest；后验复验另存文件。

A4受控失败仅将原生唯一 Langfuse exporter 的目标改为本次创建的127.0.0.1接收器，并替换为合成认证值；不将真实Cloud密钥发送到本地，不记录请求Header/Body。接收器3次实际403与日志3次导出失败一致，Reader本身无403/超时，未实施Phase B。Otel OFF不向API传Cloud凭据；负测记录明确`chain_status=NOT RUN`，不生成伪链接。

### 复现与离线验证

以下命令仅为未来明确授权后的复现说明；**本轮6 Run已用尽，不再执行付费命令**。`make obs-lab-phase-a`默认各1次、共3 Run，避免默认批次耗尽整个6 Run额度；若重复运行需先重新核对总预算。

```sh
cd server
uv sync --frozen --offline --python 3.13
uv run --frozen ruff check src tests ../scripts/obs_lab.py ../scripts/obs_lab_api.py ../scripts/obs_lab_verify.py
uv run --frozen pytest -q
uv run --frozen pytest -q tests/test_obs_lab.py
cd ..
git diff --check

# 本轮已实际执行：Run #1/#2；第二次最终Smoke通过，第一次失败原样保留。
make obs-lab-smoke OBS_LAB_ENV=/absolute/path/to/authorized-private.env
# 本轮已实际执行：Run #3/#4
server/.venv/bin/python scripts/obs_lab.py --env-file /absolute/path/to/authorized-private.env --scenarios S02 S03 --repeats 1 --max-runs 2 --timeout 150 --cloud-wait 120
# 本轮已实际执行：Run #5
server/.venv/bin/python scripts/obs_lab.py --env-file /absolute/path/to/authorized-private.env --scenarios S01 --repeats 1 --max-runs 1 --export-mode off --timeout 150 --cloud-wait 0
# 本轮已实际执行：Run #6
server/.venv/bin/python scripts/obs_lab.py --env-file /absolute/path/to/authorized-private.env --scenarios S01 --repeats 1 --max-runs 1 --export-mode failure --timeout 150 --cloud-wait 0
```

完整离线回归 **916 passed、44 skipped**（193.26秒，新增后续6项测试前）；最终定向 **37 passed**、Ruff/diff check PASS。最终验收器还仅用六个保存的State/History及四条保存Cloud链重验：模型序列/回执均匹配，四条链均通过，不重放模型。代码head `12d80244804b94f0b5e0d7ee9a113f5db87c6eab` 的[CI](https://github.com/Vc-great/kube-triage-agent/actions/runs/40438912755)六项全部PASS，Python 919 passed/47 skipped（235.87秒），AO原生审查approved。Linux与本机的跳过数量不同，Skipped均不算PASS。最终报告提交的checks另见PR #95。

新增回归覆盖完整链、缺根/缺最终Generation/缺Tool、错误Run/Session/参数/ID、时间倒序/循环父链、保留历史ToolMessage的多轮匹配、单参数标量表示、文本提到ID不能冒充ToolMessage、异步摄取补齐/预算耗尽、History缺最终模型、原生worker drain后flush及flush失败不改变执行结果。

所有私有原始数据只留新Worktree的Git忽略`.local/observability-lab`，0700/0600；源模型/Langfuse凭据及编码认证串审计0命中。三个共享链接均public=false。未连接真实Kubernetes，未改变正式Reader/Namespace/8s/16KiB、Repair/HITL、Memory、Checkpoint或SSE。没有修改旧Worktree、稳定数据库/卷/端口或其他项目资源。

### 回退与边界

回退本轮新PR提交即可恢复旧Lab入口；正式服务的原有入口和配置从未改变。只关闭本次记录的进程/容器，不能执行全局down/prune。现有合成证据保留以便复核。A0–A5全部PASS后只报告Phase A READY FOR PHASE B；Phase B/#92仍须后续任务，不自动实施，不关闭#91。

---

## PR #94 历史报告（原样保留事实，不代表本轮状态）

权威 Gate：[已合并设计 §5](plans/issue-91-observability-fault-lab.md#5-唯一权威验收-gate全部初始-not-run)。本报告仅记录实测，不降低或替代 Gate。

### 当时结论

**Phase A BLOCKED / STOP；Phase B NOT RUN。** 最新第三批是用户单独授权的一次 S01（最多 1 Run），使用新账号未注释配置与实验 API 专属 33210 代理，已通过 Cloud API 唯一关联真实 Trace：[S01 实际 Trace](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/71131804848f292fa6f215d7db86836d)。无 exporter 错误，但 Cloud 仅查到 1 个 Generation、2 个 Tool，本地为 2 次模型决策，完整 LLM→Tool→LLM 未证实，A3 不得 PASS。S02/S03 未运行，不能宣称 Phase A 完成，不进入 Phase B，不关闭 #91，不实施 #92。

前两个独立 S01 Smoke 各运行 1 Run，Aegra 终态均 success；每批旧账号 OTLP 均两次 403、Cloud 0 rows。后续获授权的无 Span 代理诊断得到明确错误：使用量阈值超限，摄取暂停；更换账号后的空批次接口测试恢复 200。历史失败不能删除或被新结果改写。

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

完整 pytest：**889 passed / 44 skipped**（177.18 秒；新增失败摘要测试前）。Provider/部分批次防护测试后定向复验为 12 passed；本次新增 API 代理绕过测试后：**15 passed**，Ruff 与 diff check 通过。Skipped 项不算 PASS。未修改前端，不以本地前端测试作为证据。此前 a64cf11 的 6 项 CI 与 AO 原生审查已通过；最新提交以 PR checks 为准，未完成时不能标 PASS。

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

运行需要 Docker、已有 `pgvector/pgvector:0.8.7-pg18-bookworm` 和 `redis:8.4.7-alpine` 镜像及 AO_SESSION_ID；不拉取镜像，不复用稳定 PG/Redis。实验入口仅允许与既有原生 deep-demo 相同的 CPA endpoint（精确 URL 白名单），保留 TLS 校验，不继承 Host proxy 环境变量。最新配置仅给 API 子进程设置 `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:33210`，`NO_PROXY/no_proxy=localhost,127.0.0.1,::1,192.168.31.110`：Langfuse 走指定代理，回环服务与已批准的内网模型直连。不传给 Mock，不修改系统代理或正式 `dev.py`。Runner 的只读 Cloud 客户端仍显式禁用代理，本次该路径查询成功；本轮没有扩大改动到 Runner 网络策略。

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

### NO_PROXY 修复后的单次授权复测

用户仅授权添加实验 API 的 NO_PROXY/no_proxy、离线测试和一次 S01 Smoke；本次未扩大为 S02/S03 或 Phase B。代码修复 `3571c63` 先推送后执行以下命令，最多 1 Run、并发 1、Run 超时 150 秒、Cloud 查询上限 120 秒；实际因 exporter 403 提前停止，只做既有 Run 的有界只读 Cloud 证据恢复：

```sh
server/.venv/bin/python scripts/obs_lab.py \
  --env-file /absolute/path/to/authorized-private.env \
  --scenarios S01 --repeats 1 --max-runs 1 --timeout 150 --cloud-wait 120
```

| 项目 | 2026-10-26 授权复测实际结果 |
| --- | --- |
| 批次 | `issue91-20261026-225152-165fc8` |
| 时间窗 | 14:51:52–14:52:15 UTC |
| S01 Thread / Run | `0cdcbc5f-228e-4d72-afd2-a2e563fdc6bf` / `10e6dc40-fb00-4a25-ab11-cb18972b6656` |
| 模型与协议 | `gpt-6-luna`；4 次模型决策、3 次 Reader 调用、Tool ID 配对通过；Aegra success、SSE 无 error；不等同诊断质量 PASS |
| OTLP | 两次 HTTP 403，正文为通用 Forbidden；没有足够证据确定响应来源 |
| Cloud v2 | 0 rows、ingestion_pending；无 Trace ID/URL，不猜测 |
| 停止 | Runner 自行非零退出：Cloud exporter 失败，不继续模型 Run；无额外 Run、未进入 B |
| 清理/审计 | 本次实验容器和 API/Mock 已关闭，既有 `kta-issue78-pg` 保持运行；目录 0700、文件 0600；模型/Langfuse 配置凭据命中 0 |

离线测试模拟系统 HTTPS proxy，验证 Japan 请求不再选择代理，而其他域名仍可选择系统代理，并验证大小写两字段仅存在于 API 环境。**绕过代理后仍403，说明此前发现的代理差异不是已证实的唯一根因；不能宣称 Cloud 写入权限已恢复。** 本次不再重试写入，后续须重新明确授权。

### 新账号与 API 33210 代理后的唯一授权 S01

2026-10-27 用户更新私有配置，旧组已注释；安全解析仅使用未注释组，存在未注释重复键时仍拒绝启动。用户随后仅授权 API 的 33210 代理、一次 S01（最多 1 Run）及有界 Cloud Trace 验证。代码提交 `0fb58d3`，运行命令与上一节相同，`--scenarios S01 --repeats 1 --max-runs 1 --timeout 150 --cloud-wait 120`；未自动补跑、未运行其他场景。

| 项目 | 2026-10-27 实际结果 |
| --- | --- |
| 批次 | `issue91-20261027-091807-60f9a6` |
| Run 时间窗 | 01:18:15.152854–01:18:25.607849 UTC |
| S01 Thread | `9947eab1-7ab0-4d22-be07-12d7d6f31daf` |
| S01 Run | `f39c0c05-b186-4678-9b99-004444794bad`（不是 Trace ID） |
| 模型/工具 | `gpt-6-luna`，本地 State 2 次模型决策、`pods_get/pods_log` 共 2 次，Tool Call ID 配对通过；Aegra success，SSE 无 error；不外推诊断正确 |
| 导出 | exporter failure_count=0，无 403；Runner 退出码 0 表示协议/Trace 关联检查成功，不等于 A3 或全部 Gate PASS |
| 实际 Cloud Trace | `71131804848f292fa6f215d7db86836d`；[真实链接](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/71131804848f292fa6f215d7db86836d) |
| Cloud 唯一关联 | 同一认证项目返回 project ID；Session 与可信 Run metadata 唯一映射到上述实际 traceId；在 120 秒预算内按 Session 与实际 Trace ID 分别分页只读查询 |
| Cloud Observation | 两种读取均 8 条：1 GENERATION、2 TOOL、5 CHAIN；两条 Tool 均在首个 Generation 结束后开始，共同父节点为 tools CHAIN；完整根节点和尾部 Generation 在预算内未查到 |
| 完整链路 | timeline_status=UNKNOWN、tool_call_id_status=NOT RUN、chain_status=UNKNOWN；不能用本地第二次模型响应代替 Cloud 尾部 Generation 证据，不为补 Trace 重跑模型 |
| 链接访问 | Cloud rows 的 public 均 false；链接须由有该新项目权限的账号登录查看；人工 UI 访问 NOT RUN |
| 清理/隐私 | 本次 API/Mock 和实验容器全部退出；既有 `kta-issue78-pg` 保留；输出 0700/0600，模型/Langfuse 配置凭据命中 0 |

当前离线测试 15 passed、Ruff/diff check PASS。代理选择测试已改为验证 Japan 明确使用 33210，回环 MCP 与已批准内网 Provider 不使用代理；仅 API 子进程收到代理配置。真实 Trace 已摄取和可唯一关联；完整链路仍缺证据，按停止边界收尾，不增加 Run 或进入 Phase B。

原始合成 State/History/SSE/Cloud rows 与日志位于 Git 忽略的 `.local/observability-lab/<batch_id>/`，目录 0700、文件 0600。不提交原始轨迹、密钥或项目私有信息。

## 逐 Gate 状态

| Gate | 状态 | 证据/缺口 |
| --- | --- | --- |
| A0 | PASS | 最新 main/锁版本核对；独立容器、端口、进程；test/Repair OFF/无 kubeconfig；未触碰 PR #90 |
| A1 | BLOCKED | 三批各 1 次 S01；最新模型/协议成功，S02/S03 未获本轮运行授权且未执行 |
| A2 | BLOCKED | 最新 S01 已 Cloud VERIFIED 并有实际链接；S02/S03 仍未验证，人工 UI NOT RUN，不以单场景冒充全部通过 |
| A3 | BLOCKED | 最新 Cloud 1 Generation/2 Tool 与局部父子关系可见，本地 2 次模型决策；尾部 Generation/完整树与 Tool Call ID 云端核对未证实，链路 UNKNOWN |
| A4 | NOT RUN | 离线回归通过、凭据审计 0 命中；真实 OTel OFF/网络故障行为对照未运行 |
| A5 | BLOCKED | 前两次 Smoke 非零，最新一次退出0且真实 Trace关联成功；但A1–A4未全部满足，即便CI通过也不能判收口 |
| B0–B5 | NOT RUN | 未通过 Phase A，禁止进入 Phase B |

## 失败记录与恢复边界

1. 第一轮在模型和容器启动前因硬编码本机 proxy 7890 不监听而返回 URLError，0 Run。一次无凭据 Host 诊断确认直连 Japan HTTPS 正常，测试入口改为明确直连；不更改正式启动器或代理服务。
2. 首个真实 Smoke 如上，模型成功但 OTLP 403，Cloud Gate 阻塞。按设计停止，不自动重发模型补 Trace。后续补充启动前失败 manifest 保存、导出错误脱敏摘要、中断和协议异常证据保存。原生审查后进一步加入 Provider 精确 URL 白名单、逐 Run 起止时间与异常批次只读 Cloud 证据恢复；该轮修复仅离线测试。
3. 只读定位发现 requests 仍可能选中 macOS 系统代理，而 REST 查询显式绕过代理。用户随后单独授权实验 API 的 NO_PROXY/no_proxy 最小修复和 1 Run 复测。本次复测仍两次 403、Cloud 0 rows，已再次 STOP；没有因为修复假设而标 PASS，也未继续 Phase B。
4. 用户明确要求通过本机 33210 代理诊断；项目 GET 200，两个无 Span 空批次 POST 均 403，脱敏 JSON 明确为 `Ingestion suspended: Usage threshold exceeded. Please upgrade your plan.`。旧账号摄取被用量阈值暂停，而非已证实的单纯代理故障；没有修改套餐或凭据。用户自行更新账号后，一次项目 GET 和一次空 OTLP POST 均200，没有模型/Span调用。
5. 最新一次真实 S01 如上，已解除本次403症状并提供实际 Cloud链接，但完整 LLM→Tool→LLM仍不能确认。未进一步修改exporter/生命周期/正式Graph或新增模型调用来补证据。

旧账号的403已有明确使用量阈值错误，新账号已实际摄取 S01 Trace。当前剩余问题是有界查询未证实完整链路，后续排查或复测需明确授权，不能自动扩大到S02/S03或B。任何恢复优先只读核对既有 Trace，不为补索引重复付费 Run；真实模型复测仍须显式限定 Run 数。

回退：本 PR 仅增加入口/测试/说明与 Make targets，不改变正式服务默认值。退出启动器会关闭其创建的子进程和容器；数据库存储为临时数据，不影响现有卷。失败后先查看本批次资源记录，仅清理本批次标识的残留资源；不得全局 `docker compose down` 或 prune。删除本任务私有输出前由用户决定是否保留反例；回退代码可 revert 本 PR 提交。
