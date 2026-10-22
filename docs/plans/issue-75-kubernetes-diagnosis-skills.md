# Issue #75 — Kubernetes Diagnosis Skills：原生按需加载与只读诊断知识

> - Issue：[Issue #75](https://github.com/Vc-great/kube-triage-agent/issues/75)；关联 [Core Demo PR #66](https://github.com/Vc-great/kube-triage-agent/pull/66)、[Evidence Reviewer S1 PR #74](https://github.com/Vc-great/kube-triage-agent/pull/74)、[Issue #69](https://github.com/Vc-great/kube-triage-agent/issues/69)。
> - 状态：**Proposed — Planning PR（仅文档）**；目前**无 Skills 运行时代码或本任务测试 PASS**。
> - 设计基线：2026-10-22，`main=0a11fcf85d6d00b412502c6181fbbb4a8168ee43`；最新 main 只包含 Evidence Reviewer 的 **S1 原生安全/证据 PoC**，非 S2 Web/S3 对照最终完成；#69 仅有已合并规划 PR #70/#71，实施仍不可在当前 main 确认。实施前需重新 fetch、核对其他 PR/Worker。
> - 依赖：`server/pyproject.toml` 固定 `deepagents==0.7.28`、`aegra-cli==0.10.8`；实施时以 `uv.lock` 和真实安装行为为准，**不自动升级**。
> - **唯一权威验收标准：本文第 6 节 S0–S9。** Issue 仅是需求入口，不另维护同名 Gate。
> - 本次授权仅为 Issue + 文档 Planning PR。规划 PR 经人工审阅并合并到 main 后，才启动 AO/Codex S1→S3；未获批不得调用付费模型或真实 Kubernetes。

## 1. 为什么做、现状核对

### 本次真正解决的问题

当前 Deep Agents Planning Demo 依靠系统提示词与通用模型选择四个 Reader 诊断 K8s 故障；针对 CrashLoopBackOff、OOMKilled、ImagePullBackOff，经常需要相似但不相同的证据调查流程。希望验证 **Deep Agents Skills（SKILL.md 领域指南）渐进式加载** 是否有助于提升工具选择、证据引用和报告一致性，而不是把所有流程重新硬编码到 Prompt 或新增一个 `@tool`。

**Skills = 知识指导，不是权限 / MCP / 自动修复。** 诊断真正执行仍由四个已有 Reader；事实仍来自当前轮有效 ToolMessage，Skill 文本不是实际集群状态，也不能授权 Repair。

### 已合并、可复用

- `server/src/kube_triage/deep_diagnosis_planning.py`：`create_deep_agent`、原生 `TodoListMiddleware`、`PlanningBoundary`、四 Reader、`write_todos`；现有 P0 只允许五工具，决定/Reader/Todo 各有预算。
- `server/src/kube_triage/deep_diagnosis.py`：Reader schema / 权限 / Namespace `kube-triage-demo` / 当前 Pod UID / Tool ID 与 16KiB 原始结果验证。
- `server/src/kube_triage/deep_diagnosis_review.py`：#72 S1 原生 Reviewer 离线 PoC，**尚未注册正式 Web 入口**，有其独立 ContextVar 执行和证据签记方案；本任务不依赖和不改造它。
- `server/aegra.phase-b1.json`、`server/src/kube_triage/deep_diagnosis_planning_entry.py`、`scripts/dev.py`、`Makefile`、`apps/web/`：已有隔离 Demo/合成 Mock、Todo、Aegra API/SSE、Web Timeline/Checkpoint，可最小复用。
- 现有正式 `server/aegra.json` 不注册 Deep Agents 实验图，Repair/HITL/Memory/正式 Reader 保持原有约束。

### 关键 SDK/社区事实（固定 0.7.28）

1. `create_deep_agent(skills=[...], backend=...)` 自动装配**原生** `SkillsMiddleware`；其 `before_agent` 用 backend `ls` + `download_files` 扫描技能目录，加载 SKILL.md frontmatter 的 name/description；模型选择后经 **原生** `read_file` 读取正文。后续官方文档可能变化，不能依赖最新版未经验证的 API。
2. `StateBackend` 可用，但官方要求 `invoke(files={...})` 中的文件是 `create_file_data` 格式，不接受裸字符串。若把三份 SKILL.md 存到用户可写的 `files` State，历史已发现 Aegra `update_thread_state` 可以注入 `files`，会把**用户可控内容当系统 Skill 指令**；因此本次首选独立、**不可写的打包内置 Skill 存储**，不能将 State 当不可篡改信任根。
3. SDK 的 `FilesystemMiddleware` 默认还有其他 FS 工具；`read_file` 必须对模型可见，而 `write_file/edit_file/delete/ls/glob/grep/execute/task` 必须从模型名单和执行侧同时排除。注意 `SkillsMiddleware` 自己内部加载 Skills 需要 backend `ls`，**内部 backend.ls ≠ 对模型暴露 ls 工具**。
4. 固定 SDK `HarnessProfile.excluded_tools` 多次注册会发生并集合并；P0 的 `_HIDDEN` 含 read_file，因此**必须独立 Aegra 进程/Profile**，实测唯一 SkillsMiddleware 与模型六工具，不在同一解释器先构建 P0 再尝试反转排除项。
5. 技能列表缓存于 `skills_metadata`，旧 Thread 可能有缓存；不要允许客户端 `skills_metadata`/`pinned_skills` 伪造新技能或强制注入非白名单文件。每次 Run 的内容和完整性必须通过后端固定白名单约束。Skills 项和缓存变化的细节使用固定 SDK 负测。
6. `FilesystemBackend` 官方警告不适合 Web API：即使 `virtual_mode=True` 也不提供进程沙箱，本任务不能为了读取技能直接给模型/HTTP 任意宿主文件权限。

参考：[官方 Skills 文档](https://docs.langchain.com/oss/python/deepagents/skills)、[Agent Skills Specification](https://agentskills.io/specification)、[0.7.28 SkillsMiddleware 源码](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/middleware/skills.py)、[0.7.28 create_deep_agent](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/graph.py)、[0.7.28 CompositeBackend](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/backends/composite.py)。

## 2. 目标与范围

### In Scope

1. **只读仓库内置三 Skill**：`crashloop-diagnosis`、`oom-diagnosis`、`imagepull-diagnosis`。每份符合 SKILL.md YAML frontmatter 标准，包含使用条件/不适用条件、有限调查步骤、可用 Reader 参数、观察与推断界限、负例、证据不足时的输出要求。
2. 独立 opt-in `deep_diagnosis_skills` Graph/开发模式，**仅**该 Graph 启用原生 SkillsMiddleware（Progressive Disclosure）和 SKILL 专用 `read_file`；可通过已存在 Web/Aegra Mock Demo 检验，P0 保持原样。
3. 打包技能资产（建议在 `server/src/kube_triage/diagnosis_skills/<skill-name>/SKILL.md`，通过 `importlib.resources` 仅加载本项目确切三文件）。运行时提供 SDK `BackendProtocol` 兼容的**不可变只读内存 Skill 视图**，通过 `CompositeBackend(default=StateBackend(), routes={"/skills/kubernetes/": <read-only-skill-backend>})` 映射固定 Skill 路径；**不开放宿主 FS**。若实际 SDK 可用更小的只读官方 Backend 实现，应优先复用；禁止引入泛用文件服务器、数据库或 Shell。
4. Model `read_file` 仅允许上述三条固定、规范化绝对虚拟路径；路径越界、缺文件、不匹配大小、绕过、并行超限均**调用 handler 前拒绝**；文件正文只含静态文本，不含脚本，避免人工写入 SDK 原始 `files`。
5. FakeModel/合成 Mock 测各 Skill 按需阅读、非触发、不得新增工具权限、拒绝来自日志的恶意指令、短历史/重试/Checkpoint/Graph 切换；6–9 组小型 Skills OFF/ON 测试，记录工具次数/上下文大小/证据质量；结果不得将 FakeModel 当真实 LLM 质量保证。

### Out of Scope

- 终端/CLI Skills、用户上传、在线插件市场、自学习技能、动态 `pinned_skills`、MCP Resources/Prompts、RAG/Vector DB、Skill 执行脚本、Shell/execute/Host FS、Repair、真实 Kubernetes 写入、权限/RBAC 扩大。
- 不混入原生 Summarization；不合并 #69 FS Offloading 或 #72 Reviewer S2/S3，未来如果另建集成 Graph 须单独评审。
- 不为 Skill 引入额外专用 Agent/Subagent；不通过 Prompt 假装自动加载；不修改正式 `graph.py` 或现有 Reader 执行实现。
- 不开启 Langfuse 额外外传、付费 Provider 批量 A/B；真实 CPA 调用需单独明确次数/模型/数据/时长授权。

## 3. 详细设计与权责边界

### 3.1 结构、数据流

~~~mermaid
flowchart TD
 U[Existing Browser / chat] --> A[Isolated Aegra: deep_diagnosis_skills]
 A --> G[Main create_deep_agent + TodoList / 4 Reader]
 G --> SM[Native SkillsMiddleware]
 SM -->|internal list+download| RS[(Immutable packaged Skill snapshot)]
 SM --> IDX[Prompt: three names + descriptions only]
 IDX --> L{Model needs expertise?}
 L -->|no| G
 L -->|yes| READ[Native read_file for exact SKILL.md]
 READ --> RS
 READ --> GUIDE[Skill workflow instructions]
 GUIDE --> G
 G --> MCP[Existing synthetic 4 Reader tools]
 MCP --> REPORT[Observation / Inference / Unknown]
 REPORT --> U
~~~

**推荐目录（实施路径可根据现有包结构轻微调整）**：

~~~text
server/src/kube_triage/diagnosis_skills/
  crashloop-diagnosis/SKILL.md
  oom-diagnosis/SKILL.md
  imagepull-diagnosis/SKILL.md
server/src/kube_triage/deep_diagnosis_skills.py
server/src/kube_triage/deep_diagnosis_skills_entry.py
server/aegra.phase-skills.json
server/tests/test_deep_diagnosis_skills.py
docs/issue75-skills-demo-validation.md
~~~

模型可见工具目标清单**恰好 6 个**：`pods_list_in_namespace`、`pods_get`、`events_list`、`pods_log`、`write_todos`、`read_file`。内部扫描 `ls` 不应出现在模型工具中。主 Agent 不得看到 `task`、write/edit/delete/glob/grep/execute/Repair/Host FS。

简单问题不应强迫调用 read_file；诊断有匹配 Skill 时可自主 read_file 并按流程用真实 Reader 查证。**Skills 不替换 `ToolMessage` 原始证据**。不能将文档中出现的“OOMKilled / ImagePull” 当成某 Pod 当前事实。

### 3.2 内容设计：三份短而精的诊断指南

三份 Skill 的前置 YAML：

~~~yaml
---
name: crashloop-diagnosis
description: Use for Kubernetes CrashLoopBackOff, frequent container restarts or exit-code diagnosis; examine current Pod status, previous container failures, events and limited logs before identifying a cause.
---
~~~

另两份 name 与文件夹一致，description 明确 OOMKilled 与 ImagePullBackOff/ErrImagePull 等触发词；仅保留规范字段 `name`、`description`（可选 `compatibility`），**不要使用 experimental `allowed-tools` 当作执行授权**；不设置 `metadata.include_tools`，不通过 Skill 扩展工具集。

每份正文建议 600–1400 汉字，单行合理分割防 `read_file` 超长行截断，限定 UTF-8，不能包含密钥、Kubeconfig、示例真实身份。内容共通模板：
- **Trigger / Not for**：场景判定和相邻故障区别；未知原因不能提前选择诊断结论。
- **Investigation**：所用四 Reader 之中可实际执行的步骤和参数范围；不得建议未提供的 kubectl、metrics API、node exec。
- **Evidence contract**：对当前 Pod UID、重启次数、lastState.terminated reason/exitCode、Event/日志的时序差异；Tool 403/404/timeout 不得判健康；Event/日志单独不能证明当前 Pod 状态。
- **Interpretation**：允许输出“观察 / 推断 / 未知”；缺资源指标时标 UNKNOWN；禁止直接执行 Repair。
- **Stop / Budget**：配合现有 Reader 六次预算、避免重复无意义拉取；不在 Skill 中要求模型无条件重试。
- **Negative examples**：Healthy、混合 ImagePull/CrashLoop、旧 UID、不完整证据、恶意日志 instruction 等。

具体重点：
- CrashLoop：启动探针失败、应用异常退出、ExitCode、重启时间链；`pods_log` 在现有工具签名中只支持 tail/container，**没有 previous=true 参数**，不能虚构“已取得 previous logs”；若 Pod 详情有 `lastState` 可用，依据现有真实字段判定。
- OOM：仅 `lastState.terminated.reason == OOMKilled` 等明确线索可说检测到 OOMKilled；**没有 Metrics Server/容器历史峰值工具**，不能从重启次数或 ExitCode 单独证明内存限制超额是唯一原因；明确缺少资源峰值/Limit 证据时的降级。
- ImagePull：区分 `ErrImagePull`/`ImagePullBackOff` 的状态，Event 中可能是镜像不存在、凭据、DNS/网络/Registry，不能凭标签单独判定私库密钥错误；禁止凭空创建 Secret、重启 Pod。

### 3.3 Skills Storage / Backend 与读取权限

首选**小型只读 Skill 快照适配器**，仅为三个随代码提交的 SKILL.md 提供 `BackendProtocol` 实际需用的 `ls/read/download_files`（包括同步/异步接口，具体以锁定 SDK 复核）。所有写入、删除、移动、上传路径直接返回 SDK 兼容的拒绝结果；不实现通用 Disk FS 操作和动态内容编辑。打包阶段、启动前校验：
1. Skill 名称与路径精确白名单，规范化路径后只可读取固定 Skill 根目录下的三个 SKILL.md；拒绝 `../`、编码绕过、同名前缀、符号链接和非预期资源。
2. 后端只在启动时读取静态打包资产生成不可变字节快照；记录非秘密 hash，读取时返回该快照；Thread 和客户端 State 无权覆盖其内容。若请求中的 `files`、`skills_metadata`、`pinned_skills` 可跳过来源验证或使模型读取假冒 Skill，S1 阻断。
3. `CompositeBackend` 的默认 Backend 可继续使用 `StateBackend`（兼容内部状态），但 Skills 路由指向只读快照；`read_file` 执行边界只准读取这些固定路径，不因默认 Backend 可能保存内部 Offload 而放开更多路径。
4. `FilesystemMiddleware(backend=same_backend, tools=["read_file"], tool_token_limit_before_evict=None, human_message_token_limit_before_evict=None)` 仅作为待实测的装配候选；原生 `SkillsMiddleware` 仍由 `skills=["/skills/kubernetes/"]` 自动创建。必须 introspection 验证自定义 FilesystemMiddleware 替换默认实例且没有重复装配，失效直接 STOP。
5. SKILL.md 每份有明确大小上限（建议 ≤12 KiB），模型一次 read_file 的 offset/limit 限定 ≤100 行，超过预算请求报错但不绕过文件范围。内置 Skill 可将正文压在 ≤100 行，避免依赖分页能力与单行截断。
6. 官方 `StateBackend` 预加载作为**备选**仅限更弱的离线 PoC，不能宣称不可篡改；若只读 Backend 小型兼容实现无法在固定 SDK 通过负测，先停在 PoC/报告，不擅自退化为向 Aegra 客户端开放可覆写 Skill 指令的 Web 模式。

**决策依据：** 不使用 `FilesystemBackend` / shell，因为 SDK 文档明确禁止未经隔离 Web 使用直接宿主文件访问；只读快照保留 SDK 原生 Skills 行为，同时解决本项目已知 State 写入口缺陷给 Skill 文本可信度带来的影响。

### 3.4 Middleware、输入状态和预算

- 新 `deep_diagnosis_skills` 复用原 Planning 的四 Reader 校验逻辑，但 `PlanningBoundary` 现有模型工具集合**恰好五项**；采用最小配置参数注入独立 Skill 模式第六项、并且 P0 默认仍恰五项；不复制现有 9KB Boundary，也不覆盖正式 Graph。
- `awrap_tool_call` 对 `read_file` 必须在 handler 前检查 Call ID 唯一、路径白名单、`offset/limit` 参数、每轮读取预算（建议 2 次；单次 1–100 行），禁止多 `read_file` 同一 AI 消息绕过预算；Reader/Todo 原预算不变，新增模型总决策建议 12 次上限，仅对新 Graph 生效。
- Skills Metadata 由 SDK 官方 middleware 加载，**Host/Wrapper 必须以可信后端路径定义授权**，不从用户提交的 `skills_metadata` 假冒来源推断授权或跳过 SDK 正常加载。
- 新 Graph 应显式关闭 Summarization、GeneralPurposeSubagent、Skills 工具延迟披露 / 可执行脚本；`skills=None` 的 P0 和正式路径保持原样。
- 原生 read_file 结果仍要遵守 ToolMessage ID/status 协议；File 内容本身属于开发者维护的静态指南，但它不提供运行时证据。遇到无法加载 Skill/校验失败时，不得隐式用任意外部文件补足；可报告“Skill unavailable”，继续按现有严格 Reader 边界执行普通诊断，不把失败伪装为已加载。
- 旧 Thread/Checkpoint 不自动迁移到新 Graph，建议启动新 Thread；设计要验证多线程技能内容一致、Refresh/Resume 不跨线程复制动态 State，取消不造成隐藏写入。
- 即使 Skills 是只读，StateBackend 仍有已知 `files` client update 旁路；隔离 Demo 仅合成 Mock，不能将其推广到真实生产环境/用户 Skills。

### 3.5 Web 演示和评价

推荐新增独立 `make dev-deep-skills-demo` Profile，复用已有 Supervisor、合成 Mock Reader 与登录/端口/停止流程；`server/aegra.phase-skills.json` **只注册** Skill Graph，避免同进程注册 OFF Profile 合并排除项。若自动浏览器测试可用，展示：
1. CrashLoop 场景 → 模型识别对应 Metadata → `read_file` 加载指定 SKILL.md → Reader 取证 → 中文诊断；
2. OOMKilled / ImagePull 类似；
3. 普通“你是谁” → 不调用 read_file；无关 Skill 不被完整读入；
4. 文件读取失败 / 403 / 错误 UID → 明确证据不足，不把 Skill 当作可信状态。
页面只复用 Timeline Tool Call 与 Todo；不要求文件浏览器/上传管理页，也不展示隐藏思维。若 UI 未明确标识，可以展示 “read_file <skill>/SKILL.md” 的已有工具事件，不能伪造“已加载”状态。

最小 A/B：**6–9 个冻结合成用例（每种故障至少一例，再加 Healthy、UID 变化、403/Prompt injection）**；Skills OFF/ON 尽量保持相同模型、工具、预算和 Fixture，OFF 不应因为减少 read_file 消耗而被额外压低决策预算；量化 Skill 选择、错误技能加载、Reader 次数、来源引用完整性、延迟/Token（只统计实测），手动标注报告结构质量。FakeModel 验证协议与路由，不证明真实模型智能收益；如无经授权的真实 CPA，则真实模型质量结果 `NOT RUN`。

## 4. 选型与风险

| 方案 | 收益 | 风险/代价 | 决策 |
| --- | --- | --- | --- |
| **A：内置三 SKILL.md + 原生 SkillsMiddleware + 固定只读内存路由** | 真正渐进加载，保留 Web/State/MCP 约束，不把 Skill 指令放在客户端可篡改 State | 少量 BackendProtocol 适配代码、锁定版本需做预研 | **首选** |
| B：将三份指南直接并入 System Prompt | 简单 | 非原生 Skills，不证明按需加载，Token 常驻 | 仅作为 A/B 基线，不是交付方案 |
| C：客户端 StateBackend(files=...) 注入技能 | 代码少 | Aegra State 写入旁路可篡改可信指令、Checkpoint 膨胀；需追加安全约束 | 不作为 Web 主方案 |
| D：`FilesystemBackend(root_dir=...)` | SDK 原生省事 | Web 场景可触及宿主文件、不具有强沙箱；增加权限风险 | 不采用 |
| E：Skills+Subagent+Filesystem 一次集成 | 功能多 | #69/#72 未完成阶段互相耦合，难以定位问题 | 不采用 |

风险：模型错选 Skill、把 Skill 当事实、Prompt injection 将日志提升为规则、Skills metadata 被客户端覆盖、多个 Profile 的 excluded_tools 联合、read_file 超边界、版本 API 与实施设计不符、过度复杂的自研 Backend。

回退：停用新 Aegra Skills Profile、保留原 `make dev-deep-demo`；删除新 Graph 注册即可取消功能，原有正式 `agent`、P0、Reader/Repair/Memory/Checkpoint 不动；不删共享 DB/卷。只清理本任务创建的独立实验资源。

**立即 STOP**：无法证明 Skill 内容与固定包资源一致；可访问任意 Host FS / 非白名单文件；Skills 意外放开 Reader/Repair、跨 Thread 私有 State；需要修改原 P0 的工具约束、真实 K8s 连接、付费调用/新端点、升级 SDK 或将 Reviewer/Offloading 引入本 PR 才能继续；不可依靠 Prompt 抵消越权。

## 5. 任务分阶段

| 阶段 | 实施范围 | 交付物 | 进入下一阶段 |
| --- | --- | --- | --- |
| **Planning（本 PR）** | 只建 Issue/设计文件；不运行或提交业务代码 | 纯文档 Planning PR、Refs #75 | 人工审阅并合入 main |
| **S1：官方 API 与安全加载 Spike** | 锁定 0.7.28、三个 `SKILL.md`、只读 Backend、SDK SkillsMiddleware 装配、渐进读取、白名单与 State 负测；FakeModel + 合成 Fixture | 独立 PoC 测试、精确工具清单、负测报告 | **S0–S4 全 PASS** |
| **S2：隔离 Aegra/Web** | 新 Graph/entry/启动 Profile、现有 Timeline/Todo、Checkpoint 和 Thread/取消/恢复；仅 Mock，无真 K8s | Web Demo / 集成证据 / 使用说明 | **S5–S7 PASS** |
| **S3：对照/工程交付** | 6–9 个合成用例，FakeModel A/B、回归 Ruff/pytest/Web/CI、独立 AO Review、中文 Gate | Implementation PR（Refs #75）、总结与回退 | **S8–S9 PASS** |

最短路径：S1 在同一实现 PR 中分 commits 也可，但失败需保留证据、STOP，不得完成“文档 PASS”后直接跳 S2。真实模型测试由单独授权的可选计划执行，绝不作为已默认批准的预算。

## 6. 唯一权威验收 Gate（S0–S9）

| Gate | 核验对象 | PASS 判定 / 证据 |
| --- | --- | --- |
| **S0** | Baseline | `git fetch origin`、main SHA、#69/#72 最新 Issue/PR、固定 SDK、独立 Worktree、已有测试/边界复核；明确 #74 仅 S1，防止重复实现 |
| **S1** | Skill 规范 | 恰好三个打包 SKILL.md，frontmatter 名称/路径严格对应、description 可让模型判断场景，内容覆盖三类诊断和反例；SDK 解析 Metadata 精确为 3；不暴露支持脚本或隐藏工具 |
| **S2** | 原生 Progressive Disclosure | 有原生 `SkillsMiddleware` 实例且只实例化一次，初始化模型只见三条 name/description，不见全部正文；相关场景必须有**实际原生 read_file** 加载对应 SKILL.md；无关场景无需读取，FakeModel 轨迹验证 |
| **S3** | 来源/权限边界 | 只读固定包内容 SHA 和精确路径，客户端伪造 `files`、`skills_metadata`、`pinned_skills` 不能替换 Skill 正文或注入新技能；非白名单读、路径遍历、write/edit/delete/execute/ls/glob/grep/task、Shell/Repair/Host FS 请求在执行前拒绝；P0 只见 5 工具、新 Graph **恰 6 工具**；非法调用没有文件副作用 |
| **S4** | 预算/诊断契约 | read_file ≤2次/轮、合法 offset/limit、Reader 6 次与参数/UID/16KiB 维持；403/404/timeout、旧 UID、恶意日志不能让 Agent 声称已确认根因或健康；模型无条件复读/重试必须受 Host 预算停止 |
| **S5** | 独立 Graph 启动 | 独立 Aegra Profile 的真实 `/assistants`、Run/SSE/Checkpoint、Mock 工具链通畅，无真实 Reader/Repair；异常启动 Fail Closed |
| **S6** | Web 用户体验 | 相关场景 Timeline 可见 `read_file` 与 Reader 调用以及中文报告，普通问候不读取 Skill；刷新/取消/切 Thread 行为与真实 Graph State 一致，真人未测明确 `NOT RUN` |
| **S7** | 历史回归/隔离 | 正式 agent、P0 Planning ON/OFF、Evidence Reviewer S1、不相关的 #69、Reader/HITL/Repair/Memory/Checkpoint 不回归；不改共享 DB/无真实 K8s/未经授权外传 |
| **S8** | 可复现小评测 | ≥6 合成案例，分别记录 Skills OFF/ON 工具调用、加载匹配、错误证据引用、误判、Token/耗时；FakeModel 不能宣称 Provider 质量优于基线，真实模型若未批准 `NOT RUN` |
| **S9** | 工程交付 | 适用 `uv run --frozen ruff check src tests`、`uv run --frozen pytest -q`、若有 Web 修改则 `pnpm lint`/`pnpm build`、`git diff --check`、CI/独立 Review、中文报告和明确回退；Implementation PR `Refs #75`，逐 Gate 实测等级与证据链接，不提前关单 |

S0–S4 **任一 FAIL/BLOCKED 就在 S1 停止**；不能通过把三份 SKILL.md 全部硬塞进 System Prompt、直接移除安全负测或“升 SDK 试一下”冒充功能完成。S5–S7 必须真实测试 Demo 行为；不能拿普通 Python 单元测试证明浏览器 UI 已通过。

## 7. 人工审阅要点与社区对照

- Skills 不是 Prompt 中临时插入三段文本；要用 SDK 原生 `SkillsMiddleware` + SKILL.md + read_file **动态按需读取**。
- Skill 只是开发者维护的指导文件，与实时 MCP 证据、用户授权、Tool 权限各自独立；不出现“通过 SKILL.md 获取读取 Kubernetes 新 API 的权限”。
- 固定 Skill 来源是否足以防 Aegra 用户可写 `files` 或 metadata 混淆；不得把只读内存 Snapshot 的实现复杂化成泛用文件服务。
- 不新增冗余 Agent，避免在 #69/#72 未完成时产生并行工作树冲突。
- 2026-10-22 的 SDK 与官方资料可能持续变化：执行前核对锁定 SDK 源码，所有推测性行为必须用 FakeModel 真实 assembled 实例与 State/Run 验证。

## 8. AO 交接（只在 Planning PR 合并 main 后有效）

- 仓库 `Vc-great/kube-triage-agent`，Issue **#75**。
- 设计 `docs/plans/issue-75-kubernetes-diagnosis-skills.md`（需先在 `origin/main` 确认存在）。
- 先 S1 / S0–S4，全部 PASS 方进入 S2/S3；只实现已批准阶段。
- STOP：原生 Skills 不成立、无法安全保护打包内容、越权工具、真实集群/未知付费模型出站、正式/P0 回归、未知 SDK API。
- 提交独立 Implementation PR（Refs #75）和中文 Gate 报告；未经用户批准不合并、不关闭 Issue。
