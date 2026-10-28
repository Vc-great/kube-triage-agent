# Issue #91 Phase B 最终验收与面试演示索引

权威标准：[设计 §5](plans/issue-91-observability-fault-lab.md)。本报告保留历史 STOP，不改写旧报告，不以协议成功代替业务成功。

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

## S01–S08 演示入口（本轮继续验收中）

所有链接指向同一 Japan 项目，需要项目访问权限；不更改公开共享设置。S01–S03 继承 [Phase A 已合并实证](issue91-observability-lab-validation.md)，并非本轮重跑。S04 的场景 PASS 来源于 [增量只读复验](issue91-phase-b-incremental-validation.md)，历史原生缺失与 STOP 保留。

| 场景 / 真实 Trace | 故障发现 → Span 定位 → 错误归因 → 模型响应 | trace_verified / 场景可观测性 / 原生完整性 | UI |
| --- | --- | --- | --- |
| [S01 Healthy](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/11261c84e536e52bad62a3be836213c7) | 正常对照：3 Generation / 3 TOOL，根 `7fea1fe0493c90ab`；确认Ready不外推业务端到端健康；非异常复现 | true / PASS / PASS（Phase A原严格链） | NOT RUN |
| [S02 CrashLoop](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/b4b180df4d414eae557fe6217a1207ea) | 2 Generation / 3 TOOL，根 `9cae04f569187ad1`；pods_get/pods_log取证，合成APP_CONFIG_PATH缺失日志定位启动问题；诊断质量未新增评分 | true / PASS / PASS（Phase A原严格链） | NOT RUN |
| [S03 ImagePull](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/0ee9f699494f065937f31e347477d6e7) | 2 Generation / 3 TOOL，根 `74a57b0dcb8f8100`；以工具返回的镜像NotFound事件定位拉取失败；诊断质量未新增评分 | true / PASS / PASS（Phase A原严格链） | NOT RUN |
| [S04 Timeout](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/9ae1ea2de58f98d9d390d5990a890295) | pods_log超过8秒 → reader_outcome(timeout)，Call `call_ZHhZHRft4rNVshoAMNSvVgP5` → 原生取消TOOL缺失 → 模型明确未取得日志、根因未知 | true / PASS（仅设计允许的取消例外） / **FAIL** | NOT RUN |
| [S05 403](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/a25e08ba8ce9b442d788263e0faa26bc) | 原生pods_get ERROR → reader_outcome(permission_denied) → 合成权限拒绝 → 模型只采用成功日志、保留Pod状态缺口 | true / PASS / PASS | PASS（上一会话） |
| [S06 Business Error](https://jp.cloud.langfuse.com/project/cmvpzre7e002pad0evz874brn/traces/7bcf19c5d15820fa8f15ce923f211969) | 原生pods_log DEFAULT → reader_outcome(business_error) → 外层成功/内层失败 → 模型声明无日志、根因未知 | true / PASS / PASS | PASS（上一会话） |
| S07 LLM 429 | NOT RUN，无Trace；应逐项对照代理attempt和同Trace的model_http_attempt，不把本地合成429称为Provider限流 | NOT RUN / NOT RUN / NOT RUN | NOT RUN |
| S08 Duplicate Tool | NOT RUN，无Trace；运行后由实际同名同参数调用计数判定，未触发才记NOT_TRIGGERED | NOT RUN / NOT RUN / NOT RUN | NOT RUN |

S01–S03原生TOOL没有直接Call ID字段的情况，使用Generation结构化output/input、Tool名称/参数/时间与State/History建立桥接，不猜造属性；具体全部Call ID见Phase A报告。S01–S06本轮逐条审阅最终回答：S01保留快照/应用层限制，S02说明配置缺失但不猜上游原因，S03只引用目标Pod的NotFound事件，S04–S06保留上述取证缺口。审阅来源为Codex，不冒充真人独立审阅或新增诊断评分。

审阅后使用当前main的 `obs_lab_reverify.reverify`（`obs_lab_reverify.py` CLI调用的同一只读函数）对五个保存批次进行复验，绑定最终回答SHA-256，结果为S01/S02/S03/S05/S06场景及原生均PASS，S04场景PASS/原生FAIL。每批manifest/private/cloud前后SHA-256一致，未读取配置、未访问模型或Cloud、未回写旧目录。审阅、复验和源完整性JSON仅保存在本会话受限产物目录，公开报告不包含原始轨迹。

## 本轮回归与当前 Gate

独立AO Worktree从最新main创建分支 `ao/langfuse-validation/phase-b-closeout`。复用Host Python 3.13.14和uv缓存，`uv sync --frozen --offline --python 3.13`，无下载升级、无锁文件修改。Host Docker 29.7.2及锁定镜像已存在，既有 `kta-issue78-pg` 未动，未启动本轮付费Run或模型服务。

- 当前main只读重验S05/S06：均PASS，未读取凭据、未请求Cloud、未修改源证据。
- `cd server && uv run --frozen pytest -q tests/test_obs_lab_phase_b.py tests/test_obs_lab.py tests/test_obs_lab_faults.py`：**116 passed，32.63秒**。
- `uv run --frozen ruff check src tests ../scripts/obs_lab*.py`：PASS。
- 完整后端回归：执行中；本PR CI：NOT RUN，不能以历史CI代替。
- 本会话UI在S01链接显示Sign In，当前UI验证NOT RUN；不将其他会话登录状态当成本会话通过证据。

| Gate | 当前状态 | 依据 / 缺口 |
| --- | --- | --- |
| A0–A5 | PASS（既有实证） | Phase A报告与#95；本轮不重跑 |
| B0 | PASS | S04–S06真实Mock注入和合法Reader路径；确定性回归通过 |
| B1 | PASS | S04受限降级、S05/S06完整原生及业务证据与回答审阅；S04原生FAIL保留 |
| B2 | NOT RUN | S07未运行，无SDK实际重试/Provider转发/Cloud同Trace证据 |
| B3 | NOT RUN | S08未运行；离线度量测试不代替真实Run |
| B4 | BLOCKED | S01–S06有真实链接；本轮计划S07/S08尚未运行，UI单列 |
| B5 | BLOCKED | B2/B3/B4未完成；本轮CI/最终回归待核实；不建议关闭#91 |
