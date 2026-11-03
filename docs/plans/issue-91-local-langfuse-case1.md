# Issue #91：本地 Langfuse 面试案例一 — 工具失败后的执行与回答评价

> - 关联 Issue：[Observability Lab #91](https://github.com/Vc-great/kube-triage-agent/issues/91)
> - 状态：Implemented on branch；Planning PR 已合并，本地实验完成；实现 PR 待审，尚不宣称已进入 main。
> - 规划 PR：[Merged #102](https://github.com/Vc-great/kube-triage-agent/pull/102)
> - 设计基线：2026-11-03，已执行 git fetch origin，origin/main=`4bb2153380e0a79f21cf9e291b85b4ca6a77c05e`。
> - 当前阶段：实施基线 `d81d1588451821436c35ce0ef1614c59a7e73e3d`；首次交付 6/6 Run，实际结果、入口与局限见[案例教程](../langfuse-case1-guide.md)。下文保留批准时的设计；历史 NOT RUN 记录不追溯覆盖。
> - 本地案例的权威验收标准：本文件 §5。原 #91/#92 的云端 Gate 仍以[原设计](issue-91-observability-fault-lab.md)为准，本文件不追溯改判历史结果。
> - 约束：[AGENTS.md](../../AGENTS.md)、[协作工作流](../agent-workflow.md)、[计划规则](README.md)。

## 1. 目标、现状与范围

完成可重复演示的“真实模型＋合成 Mock MCP＋本地 Langfuse”案例，分别回答：
1. Aegra Run / SSE 是否正常结束？
2. 工具是否真正取得所需证据？
3. 最终回复是否承认失败、是否有证据支持、是否夸大任务完成？

交付三个场景各两次真实 Run、真实 Trace 索引、Markdown/静态 HTML 报告、中文逐步查看教程和三分钟面试讲稿。运行结果不预设成功，不自动补跑挑选成功样例。

### 已核对事实

- PR #93 原规划、#100 Phase B 验收和 #101 Phase C 入口已经合并。旧工作目录中的 Proposed 文档落后于远端事实；Issue #91 正文也存在“保持 Draft”的历史描述，PR 当前 merged 状态优先。
- 主线已有 `scripts/obs_lab.py`、`obs_lab_verify.py`、`obs_lab_reverify.py`、真实 Aegra Thread/Run/SSE、S01/S05/S06 合成场景、独立 PG/Redis/API/Mock 生命周期及证据校验。复用，不新建平行 Runner。
- 主线 `scripts/dev.py:read_langfuse_env` 仍仅接受 Japan Cloud；`Cloud.get` 和校验器中的链接硬编码 Japan 地址。不能只改导出地址，否则读取目标与凭据目标会错配。
- 用户原工作目录有未提交的本地接入兼容修改及其他工作，不能覆盖、整批提交或直接移植。实施时只按本方案独立重现最小兼容变更。
- 主线模型客户端 timeout=30、max_retries=1；Runner 每 Run 最多 4 次模型决策、6 次工具调用。Provider 限域仍保留。
- 现有 Runner 要求 AO_SESSION_ID 归属标签、固定 Mock 端口 8000、有效锁定环境，且拒绝启动目录中的 server/.env。不能通过覆盖环境或删除用户文件绕过。
- 当前本地已有 ScriptedModel Trace，只证明此前本地合成链路可见，不是本次真实模型案例证据。

本版不扩展 #92 自动评测、LLM Judge、Summary、RAG、Repair、正式 Web 界面或生产部署。不新增业务 HTTP API，不修改 Reader Schema、白名单、Namespace、8 秒超时和错误处理语义。

## 2. 场景与判断口径

| 场景 | 复用数据 / 故障 | 必须检查 | 合格回答 |
| --- | --- | --- | --- |
| S01 正常查询 | 既有 Healthy fixture（sample-e） | 模型→工具→模型、参数与返回证据、State/History Call ID | 根据观测描述 Pod，不把 Ready 等同业务整体正常 |
| S05 权限拒绝 | 既有 pods_get 合成 403 | 原生 Tool 错误、permission_denied 业务结果、后续 Generation | 明确受限和证据缺口；不编造 Pod 状态，不声称已改 RBAC |
| S06 业务失败 | 既有 pods_log 外层成功、内层 ok=false | wrapper_success 与 business_error、模型是否收到错误结果 | 明确日志读取失败；可作其他证据支持的有限判断，不引用未取得的日志 |

沿用既有合成问题和 fixture，不在 Prompt 中泄露预期答案，不强制模型工具调用。未调用目标工具记事件结果 NOT_TRIGGERED；不伪造 Tool/Generation。

报告分别呈现：
- execution：Run 终态、SSE 异常、模型调用及预算。
- tool：实际调用、原生状态、业务结果、Call ID 配对、证据获取情况。
- answer：逐条审阅最终回复；是否承认故障、引用真实证据、表达判断范围。

实施代理逐条填写回答评价与依据，记录 `source=agent_review`、rubric 版本、回答哈希；不得标为 human 或伪造独立审阅。缺审阅为 UNKNOWN，回答不合格为 FAIL，不能凭字符串命中宣称诊断正确。

既有 scenario_observable / native_trace_complete / diagnosis_behavior 等判定及历史 STOP 保持原样；新增教学视图解释不同维度，不修改旧 Gate 来让报告变绿。纯回答质量 FAIL 不冒充基础设施失败，也不触发自动重试。

## 3. 实施设计

### 3.1 唯一目标与配置边界

- 将现有安全 dotenv 解析的地址白名单扩展为原 Japan HTTPS 地址及 HTTP(S) loopback（localhost、127.0.0.1、[::1]，可带合法端口）。仍拒绝 URL 用户名/密码、查询串、片段、非根路径、非允许主机和非法端口。
- 保留源文件普通文件、当前属主、0600、非符号链接、大小/重复字段校验及无敏感值报错；只提取接入和模型所需字段。
- 对既有 Cloud API 客户端及 Trace URL 构造显式传递同一个已规范化 base URL；export、项目查询、observations 查询、报告链接保持同源。拒绝重定向，不回退到云端。保留旧调用方与旧报告的 Japan 默认语义。
- 本案例入口额外要求 loopback，不接受 Japan 地址。模型调用前读取 `/api/public/projects`，要求唯一项目且 id=agent-lab、name=Agent Lab；不匹配则 BLOCKED，不自动选择或创建项目。
- API 查询使用项目 API Key，登录账号密码只属于 UI，本实验不读取或转发账户初始化字段。
- 用户明确指定的原工作目录根 .env 是本案例唯一配置源，实施时经显式 `--env-file` 传入其绝对路径；不得搜索其他 Worktree 凭据、复制 dotenv、source shell 文件或传递全量环境。公共文档不记录个人绝对路径。
- 从已批准主线创建独立 Worktree，运行目录没有其他 dotenv。只复用合规字段与已授权模型/Provider；若与原 Runner 的 Provider 边界不一致，停止并报告，不放宽白名单。
- 本地 Langfuse 直连；模型沿用选定配置和已授权网络方式。检查现有 Runner 的代理假设，不能为了运行自动切换代理或绕过 TLS。

### 3.2 入口、隔离与预算

拟新增入口（Planning PR 本身不实现命令）：

```bash
make langfuse-case1-preflight
make langfuse-case1 SCENARIO=S01
make langfuse-case1 SCENARIO=S05
make langfuse-case1 SCENARIO=S06
make langfuse-case1-report BATCH=<实际批次ID>
```

使用薄封装调用既有 Runner、采集和校验函数；不复制整个 Runner，不新增服务。新增 CLI 参数仅服务学习入口，业务 API/State 无变更。

- 首次交付建立持久化 case1 活动清单，分配唯一活动 ID、子批次和已启动 Run 数。总上限 6，每场景最多 2，并发 1；每次执行原子锁定并预占预算，重复命令不得无提示重跑，崩溃后已启动/不确定请求保守计入预算。
- 用户未来主动开始新的学习活动使用显式新活动选项；首次交付不自动创建第二个活动。报告重建不能占用模型运行入口或增加 Run。
- S01 第一条作为 Smoke，核验实际 Provider、Run/SSE、证据及本地摄取后再发第二条。固定顺序 S01→S05→S06，每个场景完成证据和回答审阅后再进入下一个。
- 每 Run 整体超时 150 秒，模型决策≤4、工具执行≤6，保留当前 SDK max_retries=1，不新增 Runner/后台任务重试。不把最多 6 Run 误称为最多 6 次 Provider HTTP 请求。
- Run 超时后先取消/终止任务独占执行并确认子进程退出，再允许下一操作，避免后台请求继续消耗预算。
- 配置、Provider、协议、隔离或 exporter 错误立即停止；后续行 NOT RUN。纯未触发和回答质量问题保留反例，经审阅后可按剩余预算继续，不重复当前样本。
- 沿用独立 API/PG/Redis/Mock，Runtime/镜像先做必要 Host capability 检查，优先复用；不自动下载。端口 8000 被占用则 BLOCKED，不操作现有进程、不改 Reader endpoint 白名单。
- 本地手工入口为任务生成专属资源归属标识，供既有 AO_SESSION_ID 标签机制使用；使用 case1/batch 附加标签，只清理记录中且标签匹配的资源，不能把其他 AO 会话资源认领为本任务。
- Repair、Memory、Summary、App History/Evidence 全部关闭；无 kubeconfig、无真实 K8s。不启动 Web，不改 Langfuse 本身的容器、数据卷或配置。

### 3.3 摄取、证据与只读报告

- 复用 Observations API v2 的时间窗、分页和真实 Trace ID 发现，按 Thread/Run、根节点与时间校验归属。项目 ID 来自已认证项目 API，不以 Run ID 代替 Trace ID。
- 每次有界摄取等待默认 120 秒，上限沿用 960 秒；摄取不完整记 PENDING_INGESTION，结束本次付费执行。后续仅查询已有 Run，不为补 Trace 发模型请求。
- 产物在忽略目录 `.local/observability-lab/` 内，目录 0700、文件 0600。活动 manifest 记录模型、版本、预算、资源与批次；私有 raw 目录保存实际 State/History/SSE、observations、最终回答及来源；原始完成批次不可覆盖。
- 报告保存每条计划 Run 的场景、时间、Thread/Run/Trace、实际链接、三类结论、原生/业务证据来源、审阅依据和缺失原因。缺失值为 UNKNOWN/NULL，不补零。
- 报告命令只做 Langfuse 读取、已有证据读取和本地产物写入，不启动模型、Mock、Aegra Run 或写 Scores。生成新的报告版本，保留旧 STOP、原始证据哈希与旧审阅。
- Markdown 与静态 HTML 索引从同一报告数据生成，HTML 转义模型/工具内容，不渲染未经处理的 HTML，不嵌入远端脚本。索引与原始证据分开，完整私有轨迹不提交 Git。
- Token 只引用可见 Provider Usage；模型价格估算与实账单分开，缺失不推算。6 条数据不用于报告生产准确率、P95 或稳定性结论。
- Trace 保留在本地，任务资源结束后按归属清理。导出失败不改变正式 Graph 安全边界或修改诊断结果。

### 3.4 教程与面试材料

教程按本地实测 UI 编写：
1. S01 Tree：定位模型→工具→模型，说明每一步的作用。
2. S05 Data/Preview：查看 pods_get 错误，再找失败后的 Generation。
3. S06：对照原生调用结果、业务观测及后续模型实际输入。
4. 查看最终回复是否引用不存在的证据，结合 State/History 核对 Call ID。
5. Timeline：比较模型/工具耗时，解释父子耗时不能累加，缺失 TTFT 不推断。
6. 查看三类评价和剩余未知；每个已验证 Trace 都由浏览器打开核对。

输入输出缺失必须标注并提供本地证据索引，不把补充报告伪装为 UI 已采集字段。只保存不含 Prompt/ToolMessage/密钥的必要 UI 截图。

三分钟讲稿按“背景→复现→定位→评价→局限”编写，用本次实测结果填充，不虚构修复前后收益或生产经历。追问覆盖 HTTP 200/Span OK 的局限、合理拒答、内层业务失败、Call ID、Mock 与真实生产的区别。

## 4. 执行阶段、兼容与停止

| 阶段 | 工作 | 下一阶段条件 |
| --- | --- | --- |
| Planning | 本文独立纯文档 PR，Refs #91；不关闭 Issue、不改旧验收 | 人工审阅且合并 main |
| 实施准备 | fetch 固定 SHA，独立 Worktree；复核入口、锁文件、凭据源和资源 | G00/G01 的代码与预检条件满足 |
| 本地实现 | 最小地址兼容、教学封装、预算与报告、定向测试 | G02/G03/G07 相关离线测试通过 |
| 实验 | 先 S01 Smoke，再按预算完成场景，逐条审阅与 UI 核验 | 运行事实、失败及缺口已保存，不自动补跑 |
| 交付 | 报告、教程、讲稿、Implementation PR 与实际 Gate 证据 | 不自动合并 PR 或关闭 #91/#92 |

保留既有 Cloud 调用方、报告字段及原校验口径；新增 base URL 对旧报告默认解释为原 Japan 来源，不能把云端历史证据改成本地链接。#101 的 Phase C 入口不受影响。

立即停止条件：真实集群/Repair 被启用、敏感数据准备外发、项目或 Provider 不符、重复模型请求失控、预算不足、资源归属不清、需修改白名单/TLS/审批或出现正式链路回归。

回退：撤回案例入口及本次兼容代码；结束并清理本任务资源，保留私有证据和本地 Trace，不删除或迁移用户数据。

## 5. 本地案例权威验收 Gate

所有运行 Gate 初始 NOT RUN；文档完成不代表实现完成。

| Gate | 内容 | PASS 条件与证据 |
| --- | --- | --- |
| G00 | 基线与隔离 | main SHA、锁定环境、独立资源、唯一配置源可核对；工作目录修改保持不动 |
| G01 | 目标与凭据安全 | export/read/link 同一 loopback 项目；拒绝错误项目/远端/重定向/非法 URL；错误不含字段值；初始化账户不进子进程 |
| G02 | 预算与生命周期 | 活动≤6 Run、每场景≤2、并发1；重复/崩溃不重放；Smoke 失败阻断；取消后无遗留执行；只清理归属资源 |
| G03 | 实际模型与协议 | 真实 Provider 标识、Run/SSE、Tool Call 配对与 State/History 一致；每条计划 Run 有实际结果或明确未运行原因 |
| G04 | 链路与错误 | 至少一条真实失败后继续模型的链路可核对；S05 权限拒绝与 S06 内层业务失败各有实际证据；未触发不算 PASS |
| G05 | 回答评价 | 实际回答逐条审阅、理由/哈希/source 齐全；缺证据明确 UNKNOWN；回答 FAIL 可作为真实反例，不能改旧诊断 Gate |
| G06 | 本地查看与教学 | 已确认 Trace 链接逐条打开，Tree/Data/Timeline 与教程一致；提供真实索引、三分钟讲稿和追问；私有内容不上 Git |
| G07 | 报告与兼容回归 | report 不触发模型/Run/Scores；摄取延迟/分页/多候选/缺字段正确处理；HTML 转义、权限/原证据不可覆盖；旧 Cloud/Phase C 用法兼容 |
| G08 | 验证交付 | 本次范围 Ruff、相关 pytest、diff-check、链接检查、适用 CI；报告准确标明未运行和残余风险 |

测试必须覆盖：
- loopback/IPv6/端口及 Japan 兼容，URL 凭据/查询/片段/重定向拒绝，错误项目在模型调用前失败。
- S05/S06 合成 fixture 经原 Reader 路径验证；原生成功不覆盖业务失败，缺 Tool/Call ID/后续 Generation 不得推断完整。
- 六 Run 全局预算、重复执行、活动锁、部分失败、未触发、超时和剩余 NOT RUN。
- 报告模式调用模型/创建 Run 的函数一旦被调用即测试失败；原始哈希不变、审阅绑定回答、缺 Usage 保持未知。
- 相关已有 obs_lab/dev Langfuse/Phase C 回归，不因本案例改变 Reader、HITL 或 Checkpoint。

## 6. 记录与交接

| 日期 | 事件 | 状态 |
| --- | --- | --- |
| 2026-11-03 | 用户批准本地案例方案与限定真实模型实验；主线固定；创建纯文档规划 | Proposed；真实运行 0/6；所有运行 Gate NOT RUN |
| 2026-11-03 | #102 合并后基于 d81d158 独立实施；完成 S01/S05/S06 各两次真实 Run、逐条 agent_review 及六条 UI 核验 | 6/6；详情见案例教程及私有活动 case1-20261103-221120-c0624e06；实现待审 |

合并后的实施任务：读取本文件与最新主线，完成本地 S01/S05/S06 案例及 G00–G08；6 Run 总预算，失败不补跑；独立工作树、唯一配置源、只向本地 Langfuse 发送合成轨迹；提交 Implementation PR，Refs #91，不自动合并或关闭 Issue。
