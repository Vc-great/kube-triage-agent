# Issue #91 Phase B 最终验收与面试演示索引

权威标准：[设计 §5](plans/issue-91-observability-fault-lab.md)。本报告保留历史 STOP，不改写旧报告，不以协议成功代替业务成功。

## 最新结论：S07/S08 真实验收完成，待本 PR 最终检查

2026-10-28 用户明确授权 **S07/S08 各1个真实付费 Agent Run，合计最多2、串行、失败不自动补跑**；唯一配置源 `/Users/vc/code/kube-triage-agent/.env`，仅由解析器读取，不输出或复制凭据。本轮实际 **2/2 Run**，没有补跑。S07只读复验 **RECOVERED**，S08真实重复 **TRIGGERED（重复计数1）**；两者场景可观测性、原生完整性、回答审阅均PASS。全部S01–S08已在当前登录的AO Browser打开并核对最终Generation；这是代理可见UI核验，不是声称真人独立审阅。

本报告下方首次归档时的NOT RUN是历史状态，已由本节真实实测推进；历史Runner STOP均保留。B0–B4实证齐备；B5的最终head CI/原生审阅结果见[#100 checks](https://github.com/Vc-great/kube-triage-agent/pull/100/checks)及[#91最终验收评论](https://github.com/Vc-great/kube-triage-agent/issues/91)。只有这些最终检查通过才建议关闭#91；不自动关闭或合并。**S04原生取消TOOL缺陷仍为FAIL**，仅按设计的受限例外判场景PASS，不表示原生缺陷已修复。

## 2026-10-28：S05/S06 已保存实测归档

最新基线 `origin/main=b85c91a6cdeaf7fb51ddf304400b4eb26b2c386e`，#98/#99 已合并。核实 #91 无评论、#99 报告仍记录 S05–S08 NOT RUN；上一 AO 会话的 S05/S06 报告尚未提交 GitHub。本节归档其脱敏结果，新增模型 Run=0，原始 manifest、State/History、Cloud JSON、回答审阅、源文件校验和与 UI 记录保留在受限本地产物中。

S05/S06 于同日各运行1次、串行，共2 Run/4次模型客户端 HTTP 200，实际模型 `gpt-6-luna`；加历史 S04，Phase B 已使用3 Run。费用和 Provider 内部请求数 UNKNOWN。唯一配置由原会话获授权的解析器读取，未复制凭据；仅真实 LLM + 合成 Mock MCP + Langfuse Japan，未连接真实 Kubernetes 写入。

| 场景 | Run / Trace | 故障与模型响应 | 场景可观测性 / 原生完整性 / UI |
| --- | --- | --- | --- |
| S05 | `c084e2ab-112a-4541-b084-fb725cf25994` / [Trace](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/a25e08ba8ce9b442d788263e0faa26bc) | pods_get 合成403；仅据成功日志指出 APP_CONFIG_PATH 缺失，保留当前Pod状态、重启及事件缺口，未修复 | PASS / PASS / PASS（用户登录后代理实际核验） |
| S06 | `6bcb1338-60ad-4ffc-ae3b-3ffb41fc5ed9` / [Trace](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/7bcf19c5d15820fa8f15ce923f211969) | pods_log 外层成功、内层ok=false；说明 archive unavailable，无日志证据，仅据Pod详情判断CrashLoop，具体根因未知 | PASS / PASS / PASS（用户登录后代理实际核验） |

两条 Trace 均14 Observations（2 Generation / 2原生 TOOL / 2 reader_outcome），State/History与Cloud逐 Call ID、参数、请求回执、父链及时间核验通过；回答审阅来源是 Codex 离线证据审阅，不冒充真人独立审阅。实时 Runner 均因缺回答审阅非零 STOP；随后通过 `obs_lab_reverify.py` 在源目录外生成独立 PASS，未为补审阅重跑模型，原始 STOP 保留。

| 场景 | 故障 Call ID | Generation 请求 → 原生 TOOL → 下一 Generation | reader_outcome / 语义 |
| --- | --- | --- | --- |
| S05 | `call_Ja29Reed9EZPRPrheDlrHEWJ` | `1fd9b567517e96d0` → `26f62651e04f1255` → `9ff246a04e1b3a73` | `4aa53ba90774a51f`：WARNING，permission_denied，wrapper_success=false；原生TOOL ERROR |
| S06 | `call_PkBRdOSwJ1wHMfNQmwOmiHgu` | `c30ff2e1f00c2a8a` → `141d9e4959190182` → `9856315e14a5aac4` | `587795cde118f4fd`：WARNING，business_error，wrapper_success=true；原生TOOL DEFAULT |

复验绑定回答 SHA-256：S05 `f164091b37993784325e472ae58fe8af1137dbe5769dd6f40fa8784455af4f57`，S06 `337382421e1ca22a256626dee1d2f2cc1f2f941e1cca59b20113981ad3a3eae1`。原会话116项定向测试通过；专属容器与进程已清理，凭据字面值审计0命中。旧 Trace GET 接口410不代表无访问权限；public属性 UNKNOWN，不设置公开共享，不发布原始合成轨迹。链接须项目账号权限。

S07/S08 本报告首次归档时 NOT RUN；B2/B3/B5 未完成，不能建议关闭 #91。S04 已知取消 TOOL 缺失保持 native_trace_complete=FAIL；不实施 #92，不改正式 Reader/HITL/Checkpoint/SSE，不自动合并。

## S01–S08 演示入口（真实 Trace 与当前 UI）

所有链接指向同一 Japan 项目，需要项目访问权限；不更改公开共享设置。S01–S03 继承 [Phase A 已合并实证](issue91-observability-lab-validation.md)，并非本轮重跑。S04 的场景 PASS 来源于 [增量只读复验](issue91-phase-b-incremental-validation.md)，历史原生缺失与 STOP 保留。

| 场景 / 真实 Trace | 故障发现 → Span 定位 → 错误归因 → 模型响应 | trace_verified / 场景可观测性 / 原生完整性 | UI |
| --- | --- | --- | --- |
| [S01 Healthy](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/11261c84e536e52bad62a3be836213c7) | 正常对照：3 Generation / 3 TOOL，根 `7fea1fe0493c90ab`；确认Ready不外推业务端到端健康；非异常复现 | true / PASS / PASS（Phase A原严格链） | PASS |
| [S02 CrashLoop](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/b4b180df4d414eae557fe6217a1207ea) | 2 Generation / 3 TOOL，根 `9cae04f569187ad1`；pods_get/pods_log取证，合成APP_CONFIG_PATH缺失日志定位启动问题；诊断质量未新增评分 | true / PASS / PASS（Phase A原严格链） | PASS |
| [S03 ImagePull](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/0ee9f699494f065937f31e347477d6e7) | 2 Generation / 3 TOOL，根 `74a57b0dcb8f8100`；以工具返回的镜像NotFound事件定位拉取失败；诊断质量未新增评分 | true / PASS / PASS（Phase A原严格链） | PASS |
| [S04 Timeout](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/9ae1ea2de58f98d9d390d5990a890295) | pods_log超过8秒 → reader_outcome(timeout)，Call `call_ZHhZHRft4rNVshoAMNSvVgP5` → 原生取消TOOL缺失 → 模型明确未取得日志、根因未知 | true / PASS（仅设计允许的取消例外） / **FAIL** | PASS |
| [S05 403](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/a25e08ba8ce9b442d788263e0faa26bc) | 原生pods_get ERROR → reader_outcome(permission_denied) → 合成权限拒绝 → 模型只采用成功日志、保留Pod状态缺口 | true / PASS / PASS | PASS |
| [S06 Business Error](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/7bcf19c5d15820fa8f15ce923f211969) | 原生pods_log DEFAULT → reader_outcome(business_error) → 外层成功/内层失败 → 模型声明无日志、根因未知 | true / PASS / PASS | PASS |
| [S07 LLM 429](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/793ae32f6a23d420d7de4a19233660a4) | model_http_attempt Warning → 合成429未转发 → SDK真实重试并转发200 → 同一Generation恢复，模型继续工具取证并完成回答；RECOVERED | true / PASS / PASS | PASS |
| [S08 Duplicate Tool](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/162732d8b0b84ed7e1f941d1fcbf455c) | 两次同参数pods_get → 两个不同Call ID/TOOL/业务Span → 模型自述确认瞬态变化，承认两次一致不排除期间变化；TRIGGERED，重复1次 | true / PASS / PASS | PASS |

S01–S03原生TOOL没有直接Call ID字段的情况，使用Generation结构化output/input、Tool名称/参数/时间与State/History建立桥接，不猜造属性；具体全部Call ID见Phase A报告。S01–S06本轮逐条审阅最终回答：S01保留快照/应用层限制，S02说明配置缺失但不猜上游原因，S03只引用目标Pod的NotFound事件，S04–S06保留上述取证缺口。审阅来源为Codex，不冒充真人独立审阅或新增诊断评分。

审阅后使用当前main的 `obs_lab_reverify.py` 对五个保存批次进行只读复验，绑定最终回答SHA-256，结果为S01/S02/S03/S05/S06场景及原生均PASS，S04场景PASS/原生FAIL。每批manifest/private/cloud前后SHA-256一致，未读取配置、未访问模型或Cloud、未回写旧目录。审阅、CLI复验和源完整性JSON仅保存在本会话受限产物目录，公开报告不包含原始轨迹。

```sh
server/.venv/bin/python scripts/obs_lab_reverify.py \
  --source /absolute/path/to/saved-batch \
  --reviews /absolute/path/to/answer-reviews.json \
  --output /absolute/path/outside-source/new-readonly-result.json
```

## S07/S08 实测、复验与演示步骤

基线仍为main `b85c91a`，不改SDK/锁文件/运行代码。Host前置检查：配置为当前用户所有的普通非符号链接0600文件；解析器确认固定Provider白名单、`/models`包含配置模型 `gpt-6-luna`；Japan `/projects`返回原项目 `cmvpzre7e002pad0evz874brn`；33210代理可达、Mock8000空闲。只用合成Mock；`TRIAGE_ENV=test`、Repair/Memory/History/Evidence/Summary OFF，无真实kubeconfig。每批独立PG/Redis/API回环端口、PG tmpfs及本会话/batch容器标签。

| 场景 | Batch / Thread / Run | 真实计数与终态 |
| --- | --- | --- |
| S07 | `issue91-20261028-160529-60f8fa` / `09865b25-d297-45ec-8097-0f0bc28afed7` / `025d2163-e244-42fe-9df7-0c0a69c20a39` | Agent success；3决策/4 TOOL/4 reader_outcome；26 Observations；4 HTTP attempt（合成429一次、Provider转发200三次）；根 `d9ce5658577dfd9d` |
| S08 | `issue91-20261028-160823-8841b7` / `25d18400-93e5-49a4-b4ea-ff2e03322c9c` / `bd5a9e89-622a-4630-93b2-01faef6d1e02` | Agent success；3决策/4 TOOL/4 reader_outcome；22 Observations；3模型客户端HTTP200；根 `98871eba91941951` |

两场景所有决策回显 `gpt-6-luna`。本轮总计2 Agent Run、6个Generation、7次HTTP attempt（含1次本地合成429，6次真实Provider转发200）；S07的模型客户端日志计数缺失，用受控代理原始attempt及Cloud同Trace交叉确认，不伪造日志值。Provider内部请求数量和最终账单UNKNOWN，UI估算不等于账单。Phase B历史累计5 Run（S04/S05/S06/S07/S08各1），本轮2 Run授权全部用尽，不继续使用旧余量。

实际命令（记录，不是再次执行授权）：

```sh
server/.venv/bin/python scripts/obs_lab.py \
  --env-file /Users/vc/code/kube-triage-agent/.env \
  --scenarios S07 --repeats 1 --max-runs 1 --timeout 150 --cloud-wait 120
# S07显式审阅与只读复验PASS后，才执行：
server/.venv/bin/python scripts/obs_lab.py \
  --env-file /Users/vc/code/kube-triage-agent/.env \
  --scenarios S08 --repeats 1 --max-runs 1 --timeout 150 --cloud-wait 120
```

每Run≤150秒、模型决策≤4、工具≤6、SDK max_retries=1、后台重试0，S07桩最多8 attempt。两条命令均在Cloud证据齐备后因**缺少显式回答审阅**非零退出，原 `scenario_observable=BLOCKED`/STOP不改写；不是宣称Runner直接PASS。随后Codex逐条审阅State/History工具回执、Cloud最后回答和可见UI，绑定回答SHA-256，通过 `obs_lab_reverify.py --source ... --reviews ... --output ...` 写到历史目录外的新0600文件；新增模型请求/Cloud写入=0。S07 manifest/private/cloud/attempts及S08 manifest/private/cloud前后SHA-256完全一致。

### S07：合成限流、SDK重试与真实恢复

| attempt / 模型决策 | HTTP / forwarded | Cloud model_http_attempt | llm父节点 / 对应Generation |
| --- | --- | --- | --- |
| 1 / 决策1 | 429 / false | `0a9744d6dbfd74d5`，WARNING，synthetic_rate_limit | `22c93b2cebe21f53` / `dd65212b79952a3e` |
| 2 / 决策1 | 200 / true | `e6b9a7b343fbcc4d`，provider_forward_success | 同上；**同一个Generation内SDK真实重试** |
| 3 / 决策2 | 200 / true | `f7334d01ab48d446`，provider_forward_success | `582abe715e6907f4` / `605e74c6fce15a74` |
| 4 / 决策3 | 200 / true | `601b5321924380ab`，provider_forward_success | `b1ffd6628c280f27` / `5a3073112ca7a50a` |

全部位于Trace `793ae32f6a23d420d7de4a19233660a4`，与本地代理编号、forwarded、status逐项一致，完整父链和父时间覆盖子时间通过。首个429来自本地桩，**不是Provider返回的429**；attempt2才真正向原Provider转发并收到200。3个Generation对应真实3次模型决策，不能把4个HTTP attempt说成4次模型决策或补造Generation。

模型恢复后自主先查Namespace/Events，再查Pod/日志，最终据配置缺失日志和目标BackOff解释CrashLoop；明确上游配置来源未知、静态模拟数据边界、未修复。模型没有向用户声称曾观察到或处理Provider限流；恢复属于SDK请求层，最终诊断内容与恢复结果分开记录。

面试操作：打开S07 → 点首个 **model_http_attempt Warning**，看 `synthetic_rate_limit / attempt=1 / forwarded=false / status=429` → 点相邻attempt2看 `provider_forward_success / 200` → 对照同一个llm父节点和Generation → 看后续工具与最后ChatOpenAI回答。首故障字段与恢复节点已实际UI核验。

### S08：真实重复与模型自述

模型决策1调用pods_get、events_list、pods_log；决策2再次调用 **pods_get(namespace=kube-triage-demo,name=sample-a)**；决策3完成回答。相同规范化工具名/参数出现2次，因此重复计数为1，`event_result=TRIGGERED`，不填写NOT_TRIGGERED。

首次Call `call_KqyE60VyzEPP6IMw7XGbZZzV` 与重复Call `call_45z6K1IZZO50ZB8KR7luFy8U` 的Pod静态回执一致。模型最终自述“用于确认是否有瞬态变化”，但同时说明两次一致不排除期间短暂变化；这是**最终回答的解释**，不声称能够证明其未暴露的内部推理。诊断引用配置缺失日志、目标BackOff与Pod状态，并保留配置来源、退出详情和并发问题的不确定性，未修复。

面试操作：打开S08 → 对照前两次模型决策下的 **pods_get**（两个不同Call ID、原生TOOL与reader_outcome）→ 最后Generation input核对两个回执 → output看重复查询解释与证据边界。不是Runner强插工具调用，也不是通过重跑挑选重复结果。

### S07/S08 全部工具桥接

以下Call ID逐项通过Cloud Generation结构化output/input、原生TOOL名称/参数/时间、reader_outcome和State/History核对；所有业务结果均success/wrapper_success=true。

| 场景 / 工具 / Call ID | 请求Generation → 原生TOOL → 回执Generation | reader_outcome |
| --- | --- | --- |
| S07 pods_list_in_namespace / `call_CLMGNL46iaXVMaNaBvJsRX5z` | `dd65212b79952a3e` → `bf20c39afe9d5815` → `605e74c6fce15a74` | `f72ab6c3df99cb82` |
| S07 events_list / `call_21dQUUJpEs02dVYeSiaJ7BS3` | `dd65212b79952a3e` → `5c5776f870b33e0b` → `605e74c6fce15a74` | `4eba6ff0bb21e036` |
| S07 pods_get / `call_cTCLx9dpJ5xawNh2LJBCJvMh` | `605e74c6fce15a74` → `7f429dda457018d5` → `5a3073112ca7a50a` | `4537d8e8ff792c57` |
| S07 pods_log / `call_KtbRqMs1cbUQfncMCGGPynyU` | `605e74c6fce15a74` → `29af2dc209486eb3` → `5a3073112ca7a50a` | `e65fb1cfdf94a9b3` |
| S08 pods_get / `call_KqyE60VyzEPP6IMw7XGbZZzV` | `1522d2f53ed3e429` → `45c97128055829c0` → `808cb19578bc2e8c` | `975afa42784d0c03` |
| S08 events_list / `call_SlMXeu4HMJMKsPu0qNZRg8Bw` | `1522d2f53ed3e429` → `1a37189127cefc3e` → `808cb19578bc2e8c` | `12cee6999678e00d` |
| S08 pods_log / `call_bLkMF0tJhxCUapQ5QYUUqLTn` | `1522d2f53ed3e429` → `b8cc35210c93ebc0` → `808cb19578bc2e8c` | `4f1732ea221c710c` |
| S08 pods_get重复 / `call_45z6K1IZZO50ZB8KR7luFy8U` | `808cb19578bc2e8c` → `12e8598661c8eec4` → `6c61de928d091299` | `a392109935e7a959` |

## 本轮回归与当前 Gate

独立AO Worktree从最新main创建分支 `ao/langfuse-validation/phase-b-closeout`。复用Host Python 3.13.14和uv缓存，`uv sync --frozen --offline --python 3.13`，无下载升级、无锁文件修改。Host Docker 29.7.2及锁定镜像已存在，既有 `kta-issue78-pg` 未动。版本与#99锁定环境一致，含Aegra0.10.8/LangGraph1.2.14/OpenAI3.29.0/OpenInference0.1.79/OTel1.45.1。

- 当前main只读重验S05/S06：均PASS，未读取凭据、未请求Cloud、未修改源证据。
- `cd server && uv run --frozen pytest -q tests/test_obs_lab_phase_b.py tests/test_obs_lab.py tests/test_obs_lab_faults.py`：**116 passed，32.63秒**。
- `uv run --frozen ruff check src tests ../scripts/obs_lab*.py`：PASS。
- `cd server && uv run --frozen pytest -q`：**1001 passed、44 skipped，191.28秒**；Skipped不计PASS。无前端改动，本地前端构建NOT RUN。
- 上述回归对应相同运行代码；真实Run前后均无运行代码变更，未为纯文档再重复全量测试。`00cc38a`的六项CI全部PASS、AO原生文档审阅approved；本次新增实测文档后仍需核实最终head，不能用旧head代替，结果见[#100 checks](https://github.com/Vc-great/kube-triage-agent/pull/100/checks)。
- 当前会话用户登录后S01–S08全部UI访问、树及最终Generation核对PASS；S04可见2 Generation/1 TOOL，S05/S06各2/2，S07/S08各3/4，未把S04缺失改成完整。
- 两个新批次OTel force_flush completed=true、exporter failure_count=0；本会话Docker标签无剩余容器、Mock8000无监听，既有`kta-issue78-pg`仍在15478运行。仅清理本批资源，无真实Kubernetes写入或部署变更。
- 本会话产物60文件扫描（唯一配置由解析器在内存提供审计字面值）命中凭据/编码认证串0；原始证据与复验文件0600、目录0700。源证据完整性单独记录，完整轨迹与回答仅留受限产物，不提交。链接须项目权限，不改变public/共享/评分；复验/UI无Cloud写入，真实Run仅沿用原生OTel导出，不额外补报Observation或Score。

| Gate | 当前状态 | 依据 / 缺口 |
| --- | --- | --- |
| A0–A5 | PASS（既有实证） | Phase A报告与#95；本轮不重跑 |
| B0 | PASS | S04–S06真实Mock注入和合法Reader路径；确定性回归通过 |
| B1 | PASS | S04受限降级、S05/S06完整原生及业务证据与回答审阅；S04原生FAIL保留 |
| B2 | PASS | S07一次合成429、真实SDK同决策重试、Provider实际200转发；4个同Trace业务attempt与本地完全一致；RECOVERED |
| B3 | PASS | S08实际同参数pods_get重复1次，TRIGGERED；请求/回执/不同Call ID及模型最终自述可查；度量确定性样本测试通过 |
| B4 | PASS | S01–S08各实际计划Run均有真实Cloud链接，场景/原生维度及当前UI单列；S04原生FAIL保留 |
| B5 | BLOCKED | 仅待最终检查：实测、中文复现、回归、隔离/清理已完成；最终head CI与AO审阅在#100/#91记录，通过前不建议关闭 |

最终CI/审阅通过后在#91最终评论记录B5 PASS，避免用文档提交自身之前的检查冒充最终head已通过。不自动关闭Issue、不自动合并PR。残余风险：S04取消原生TOOL缺陷仍在；Mock不证明真实集群故障或修复；重复事件不保证再次运行一定发生；实际费用与Provider内部调用UNKNOWN；不实施#92的Summary/Scores/Judge。
