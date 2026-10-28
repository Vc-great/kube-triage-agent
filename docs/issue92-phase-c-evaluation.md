# Issue #92 Phase C：可复核规则评测与 Summary/Grounding 实验

权威 Gate：[设计 §3.5、§5 C0–C4](plans/issue-91-observability-fault-lab.md)。本报告是实现与验证快照，不替代权威标准。基线 `origin/main=1dd9d71c08273ea57336772b207a0407b76bfa37`；[#100](https://github.com/Vc-great/kube-triage-agent/pull/100) 已合并，采用 [#91 最终验收](https://github.com/Vc-great/kube-triage-agent/issues/91#issuecomment-6463802480) 的 B0–B5 PASS。#91 仍 OPEN；S04 原生 TOOL 缺失仍 FAIL。本次不改变任何 A/B 实证。

## 本次实现与证据等级

- `scripts/obs_lab_scores.py`：读取指定保存批次，独立校验冻结 Ground Truth/fixture SHA、Run/Thread/Trace 唯一关联，输出 `obs-lab-rules-v1`；无网络、无模型调用，不回写历史文件。源 manifest/private/cloud 全部绑定 SHA-256，结束时复查。重复或歧义身份直接 STOP。
- `scripts/obs_lab_score_upload.py`：独立 Public API 上传器；没有 SDK exporter。必须给出人工批准的精确计划 SHA 和写入上限。Cloud Project/Trace 复核、既有 ID 内容冲突检查均在写入前；单次批量 POST、180 秒总 API 预算、最多三轮回查、失败不自动重发。使用新建0600 journal；同 journal 不重复写入。超时后保留 journal，先只读核查，不能盲目换新 ID 重发。
- `scripts/obs_lab_phase_c_run.py`：独立真实运行收集入口，S09 同 Thread 逐轮实际执行，S10 单独新 Thread。S09 每轮均计入显式批准的 `max_runs`；首次观察 Summary 就停止，不保证采用成功。每轮先保存 State/History/SSE/Run，再限定 Cloud 查询，协议/关联失败即停。S09 上下文预算7200是现有保守估算值，含输出保留，不是 Provider Token。单轮30–180秒，默认150秒；每轮仍使用既有≤4模型决策/≤6工具、SDK一次重试。Summary另有原项目512输出Token/12秒边界，不能把一个Run等同一个模型请求。
- `scripts/obs_lab_context.py`：只在 S09 的隔离 API 进程安装。包装现有 `_summary_view`，从已有脱敏审计复制真实 adopted/fallback/cache状态、usage与耗时，通过原 callback 链生成 `context_summary_outcome`；不读取正文到自定义metadata，不更改正式 Graph/Checkpoint/Reader/HITL。
- S10 直接复用冻结 `issue12-blind-v1` sample-g：同名 Warning 无 UID、空日志不能确定根因；sample-noise 的 Warning 属于其他Pod。Ground Truth 不放进模型问题。Mock测试实际运行现有Graph工具链，分别产生保留未知和武断归因回答，验证规则反例。Mock不能代表真实模型质量。

## 规则口径：不是人工或 LLM Judge

每项包含 `status/value/reason/applicable/source/version`；UNKNOWN 的数值为NULL。上传为 CATEGORICAL 的 PASS/FAIL/UNKNOWN，不把UNKNOWN当作0；不适用同时记录 `applicable=false`。来源统一为 `deterministic_rule_check`，Cloud来源为API。`diagnosis_correct=UNKNOWN`、`human_review=NOT RUN`、`judge=NOT RUN`。

| 规则 | 适用对象与判定 | 局限 |
| --- | --- | --- |
| tool_protocol_valid | 有工具请求/回执的Run；唯一非空Call ID一一配对，保存History中请求参数/回执/模型序列一致，且工具参数白名单合规、观察到的决策/工具数未超预算 | 不等于原生Span完整，S04依然原生FAIL |
| fault_handled | S04–S06注入故障回执已被观测且配对，最终回答出现对应超时/权限/不可用标记 | 只检查词面；不能证明语义上正确处理。其他场景UNKNOWN/不适用 |
| evidence_uid_matched | 目标Pod与Warning Event的成功回执；UID相同为PASS，冲突/非法为FAIL，无UID/未取Event为UNKNOWN | 检查证据归属，不推断模型引用正确；无关Pod Warning不计入目标证据 |
| unnecessary_retry | 记录规范化同参调用次数 | 无时机、变化与意图的可信判据，v1均UNKNOWN；S08不因重复自动扣分 |
| grounding_rule | 成功配对回执中的冻结必要证据（故障场景可用确已发生的故障缺口）+最终回答必要词面标记；S10需要UID、弱归属/缺失、不确认根因标记 | 是rule_check，不是语义蕴含或诊断正确率。引用/否定/额外幻觉可骗过词面检查，PASS不能证明回答全部被证据支持 |

精确必要标记在 `ANSWER_MARKERS` 中版本化。新增规则语义、扩大适用范围应升版本并重新审阅；不能回写A/B结论来迎合新评分。冻结数据SHA `f29ffaf75af106562202b92ec34cc25a0025cd49ef7a924cbed0e6cdbfe9abe9`、fixtures SHA `ea5f08d05452bb1ca03a89da6ba7608efc1c7874cddc0c317dfe7e4fadd28494`，变动即STOP。

## 八场景只读实测

复用7个保存批次中的8个Run，每场景1条；S01使用最终PASS批次，首轮解析失败批次未混入。原始STOP与私有证据不改写。派生JSON在当前会话受限产物目录，未提交原始轨迹。新增模型调用、Cloud请求、Score写入均为0。

| 规则/数据 | 观察结果 | 分母/解释 |
| --- | --- | --- |
| 协议规则 | 8 PASS | 8 Run，不替代原生完整性 |
| 故障回答标记 | 3 PASS、5 UNKNOWN | 3个适用Reader故障Run，其余不适用 |
| UID匹配 | 4 PASS、4 UNKNOWN | 8 Run，无FAIL；未知不补零 |
| 不必要重复 | 8 UNKNOWN | S08重复1次不等于无必要 |
| Grounding必要标记 | 8 PASS | 8 Run，仅上述词面规则 |
| 工具回执 | 20 success、timeout/permission_denied/business_error各1 | 23个已配对工具请求；外层ok=true不掩盖内层业务失败 |
| Provider报告总Token | S01–S08依次4492/3380/3325/2514/2379/2524/5736/5925 | 来源final State中去重triage_llm usage；不含不可见内部重试或账单 |
| Trace根Span延迟 | P50约15.21秒、P95约19.98秒 | n=8；median/nearest-rank；Cloud root end-start，不是端到端Runner或纯模型延迟 |
| Runner延迟 | UNKNOWN | 8/8旧manifest缺elapsed_seconds，不把Trace延迟冒充Runner延迟 |
| 诊断正确性/人工/Judge | UNKNOWN / NOT RUN / NOT RUN | 已知正确性分母0，不输出正确率 |

这些数据是**小样本描述**，场景不独立同分布，不能用作可靠总体P95、生产SLO或模型排名。既有Tool错误是实验设计，不代表生产错误率。Token为Provider可观察usage，不估算代理私有账单。

离线命令（每个历史批次增加一个 `--source`，不请求网络）：

```sh
server/.venv/bin/python scripts/obs_lab_scores.py \
  --source /absolute/path/to/saved-batch \
  --output /absolute/path/outside-source/new-evaluation.json
```

## 云端写入与付费实验：本次 NOT RUN

当前只生成40条候选Scores（8×5）。上传字段仅稳定ID、已有真实traceId、规则名、分类值、固定timestamp、source=API、environment=obs-lab、含版本/来源/证据与GT哈希/适用性的comment；不含问题、回答、Tool正文、真实日志或凭据。脱敏范围、目标项目与精确计划哈希须先获批准，不自动沿用#91模型预算。Score ID由版本/项目/批次/Run/Trace/规则确定，timestamp固定为原Run结束时间，禁止更换ID制造重复批次。

按2026-10-28核对的[官方Scores说明](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk)和[官方OpenAPI](https://cloud.langfuse.com/generated/api/openapi.yml)，POST `/api/public/scores`接收数组；GET `/api/public/v3/scores`显式取 `core,details,subject`，分类value是字符串、关联在 `subject.kind=trace / subject.id`，不能拿旧API的numeric mapping/stringValue或顶层traceId代替。回查核对每个Score的ID、值、时间、来源、comment与真实Trace关联。模拟Cloud覆盖首次写入、重复跳过、项目/关联冲突和写后错配；真实API契约仍需批准后的实测。

以下为批准后的命令模板，**展示不构成执行授权**；配置必须来自本会话明确获准、属主/0600/非符号链接的配置文件，不复制其他Worktree的.env：

```sh
server/.venv/bin/python scripts/obs_lab_score_upload.py \
  --report /absolute/path/new-evaluation.json --env-file /approved/config/path \
  --approved-plan-sha256 <approved-exact-sha256> --max-writes 40 \
  --journal /absolute/path/new-journal.json --output /absolute/path/new-cloud-readback.json

server/.venv/bin/python scripts/obs_lab_phase_c_run.py \
  --scenario S09 --approved-max-runs <approved-turn-run-budget> \
  --env-file /approved/config/path --output /absolute/path/new-s09-batch
# S10另行独立批次，--scenario S10 --approved-max-runs 1
```

S09最多10轮只是代码硬上限，不等于已授权10个Run；必须先批准确切预算、数据与配置来源。每轮新Run、同Thread；到预算仍未出现Summary就BLOCKED，不自动补跑。真实模型/Cloud未执行前，不能将Mock adopted/fallback标为C0 PASS。

## 学习用 Langfuse Trace + Score 浏览

1. 从[八场景真实Trace索引](issue91-phase-b-closeout.md)打开有项目权限的Trace，不改变公开共享设置。先核对Run/Thread/Trace，再看Generation output工具请求和下一Generation input中同Call ID回执。
2. S04查看timeout业务Span与模型“不知道根因”的回答，原生取消TOOL仍缺失。S06外层成功、内层business_error独立看；S08比较两个同参请求的时机和回执，不把重复次数当浪费分数。
3. **当前Scores尚未上传**。批准且Cloud回查PASS后，在Trace的Scores区找 `obs-lab-rules-v1.*`，确认source=API和comment版本/哈希；展开UNKNOWN原因看本地规则报告，不能把API评分当人工评分。
4. S09实测后，在 `context_summary_outcome` 看真实audit的adopted/fallback、omitted_rounds、预算、Token/耗时；继续看主模型是否使用历史低信任参考。Generation成功不等于Summary已采纳，fallback的Token可能UNKNOWN。
5. S10实测后，对照冻结sample-g Ground Truth与实际工具回执：无UID只算弱归属，sample-noise不是目标Pod。比较最终回答与rule_check，主动寻找词面规则漏判；Run success和grounding_rule PASS都不能代替诊断正确性审阅。

## C0–C4 当前状态

| Gate | 状态 | 实证与剩余条件 |
| --- | --- | --- |
| C0 触发Summary | NOT RUN（真实） | Mock在同Thread实际Graph/checkpoint多轮触发adopted/fallback，记录阈值/usage/耗时；真实付费Run与Cloud未获批准，不能PASS |
| C1 诊断误判 | NOT RUN（真实） | 冻结GT、弱UID/无关Warning、实际Graph合成好/坏回答规则反例已验证；真实S10与输出审阅待批准 |
| C2 Scores | NOT RUN（云端） | 八场景离线评分与40条脱敏清单；上传/幂等/冲突/readback Mock已验证，真实写入和Scores v3回查待授权 |
| C3 质量指标 | BLOCKED（完整Gate） | 既有8 Run的usage、根Span延迟与规则分母已实算；完整Runner耗时、S09/S10真实结果、语义诊断质量未知，不外推总体 |
| C4 C收口 | BLOCKED | #91实证已合入main；当前PR须通过最终CI/审阅，且C0–C3仍未完成。保持Draft，不关闭#92，不实施Phase D |

本地验证：Python3.13.14，`uv sync --frozen --offline --python 3.13`复用Host缓存，无锁变更；后端Ruff通过。首次Context/A/B定向回归152 PASS；完整后端回归1028 PASS、44 SKIPPED（174.67秒），随后协议参数白名单收紧与新增用例的最终定向28 PASS（0.86秒）。最终head CI/AO审阅见PR，不能用本地结果替代。无前端代码变更，本地前端构建NOT RUN。

回退：停止本任务入口，撤回本PR的test-only适配器与脚本即可；未改变正式Graph默认配置、部署或历史证据。真实数据外传、扩权、错误Project或Score关联冲突立即STOP。无Phase D、第二exporter、真实Kubernetes写入、Repair或自动关单。
