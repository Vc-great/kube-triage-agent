# Issue #75 — Kubernetes Diagnosis Skills：原生按需加载与只读诊断知识

> - Issue：[Issue #75](https://github.com/Vc-great/kube-triage-agent/issues/75)；关联 [Core Demo PR #66](https://github.com/Vc-great/kube-triage-agent/pull/66)、[Evidence Reviewer S1 PR #74](https://github.com/Vc-great/kube-triage-agent/pull/74)、[Issue #69](https://github.com/Vc-great/kube-triage-agent/issues/69)。
> - 状态：**Proposed — pin/Resume 边界设计修订（仅文档），S1 STOP**。原 [Planning PR #76](https://github.com/Vc-great/kube-triage-agent/pull/76) 已经用户人工审阅并合并；本修订尚待人工审阅合并。main 无 Skills 运行时代码；本地 S1 试验已有失败，见第 1.1 节，不能再称“未发现问题”。
> - 修订基线：2026-10-22，`origin/main=b791cffaec0e8f0d665872bdb75ef00e3b9f2029`（#76）；原设计基线为 `0a11fcf`。最新 main 只包含 Evidence Reviewer 的 **S1 原生安全/证据 PoC**，非 S2 Web/S3 对照最终完成；#69 仅有已合并规划 PR #70/#71，实施仍不可在当前 main 确认。实施前需重新 fetch、核对其他 PR/Worker。
> - 依赖：`server/pyproject.toml` 固定 `deepagents==0.7.28`、`aegra-cli==0.10.8`；实施时以 `uv.lock` 和真实安装行为为准，**不自动升级**。
> - **唯一权威验收标准：本文第 6 节 S0–S9。** Issue 仅是需求入口，不另维护同名 Gate。
> - 本轮授权仅为修订设计并提交纯文档 Planning PR（`Refs #75`），不含原型或测试代码。本修订经人工审阅并合并到 main 前，**不继续实施**；合并后从 S1 重验 S0–S4，不直接进入 S2。不得调用真实模型或真实 Kubernetes，不合并 PR、不关闭 Issue。

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
7. 本地 S1 已复现原生 pin 恢复旁路：只读快照不能阻止 `pinned_skills` 在恢复时强制加载全部正文。`before_agent` 清理和独立前置 middleware 校验都不能覆盖已越过该 hook 的恢复点；模型包装器只看已清空的 pin 字段也不够。具体失败与拟议防护分别见第 1.1 节、第 3.4.1–3.4.4 节。

参考：[官方 Skills 文档](https://docs.langchain.com/oss/python/deepagents/skills)、[Agent Skills Specification](https://agentskills.io/specification)、[0.7.28 SkillsMiddleware 源码](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/middleware/skills.py)、[0.7.28 create_deep_agent](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/graph.py)、[0.7.28 CompositeBackend](https://github.com/langchain-ai/deepagents/blob/deepagents%3D%3D0.7.28/libs/deepagents/deepagents/backends/composite.py)。

### 1.1 本次修订依据：保留 S1 失败反例

2026-10-22，本地离线工作副本使用 Python 3.13.14、`deepagents==0.7.28`、`aegra-cli==0.10.8`、FakeModel、合成 Reader 和 `MemorySaver`；子进程阻断 socket，关闭追踪。实施前基线 Ruff PASS、pytest **859 passed / 151.95s**；S1 专项最终 **43 passed / 1 failed / 72.39s**。唯一失败为 `resume-pin`；S3 来源边界与 S4 加载预算均记 **FAIL**，其余正例不能抵消该失败。S2/S3 阶段未启动。

当时的原型以固定只读包快照提供正文；Host 在 `before_agent` 清空技能缓存和 pin，在独立 `before_model` 与模型包装器校验 canonical metadata、空 pin。最小反例保留如下（示意执行顺序，**不是本 PR 新增的程序测试**）：

~~~python
# graph: 上述旧 S1 原型；model: 记录输入的无网络 FakeModel
await graph.ainvoke(new_human_input, config,
                    interrupt_before=["SkillsMiddleware.before_model"])
assert not model.inputs
await graph.aupdate_state(config, {"pinned_skills": [
    "crashloop-diagnosis", "oom-diagnosis", "imagepull-diagnosis",
]})
await graph.ainvoke(None, config)
assert not model.inputs  # 实际 FAIL：模型仍被调用
~~~

实际统计：`model_calls=1`、`pinned_messages=3`、`native_read_file_calls=0`。三条 HumanMessage 带有 SDK 的 `lc_source=pinned_skill`，正文来自合法固定快照；没有修改 `files`、metadata 或包资源。

失败机制：暂停点已越过 Host 前置检查 → 客户端修改 pin → Resume 直接进入原生 pin hook → SDK `download_files` 并注入三份正文 → SDK 清空 pin → 模型包装器仅看到合法 metadata 与空 pin，因而放行。三份正文未经过受控 `read_file`，也不受其两次预算限制；新增 HumanMessage 还可能干扰基于最后 Human 的轮次识别，这一后果**未单独实测**。

该证据仅证明 **MemorySaver 恢复路径的强制加载旁路**，未证明任意正文替换、Host FS 读取、跨 Thread 泄漏或真实 Aegra HTTP 攻击成功。历史命令为在原离线副本 `server/` 执行 `uv run --frozen --offline pytest -q tests/test_deep_diagnosis_skills.py -k resume-pin`；此测试文件和原型尚未合入 main，不能把该命令当作当前 main 可运行的验收。

本规划 PR 不带入原型、不修改或运行该失败测试。后续实现须保留旧装配的失败 characterization 和上述禁止模型调用的安全断言，并对修订装配运行同一攻击；不得删除、skip、xfail 安全断言或把历史 FAIL 改成 PASS。旧失败记录始终保留，新装配的证据单独记录。

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
4. `FilesystemMiddleware(backend=same_backend, tools=["read_file"], tool_token_limit_before_evict=None, human_message_token_limit_before_evict=None)` 保留为装配候选。Skills 仍使用固定 SDK 原生 middleware；本修订提出用其最小派生实例替换原生同名 slot，**只禁用 pin hook**，见第 3.4.1 节。必须 introspection 验证唯一有效原生 Skills 实例、唯一 FilesystemMiddleware，扫描/钩子无重复；扩展点、装配或原生渐进加载任一不成立即 STOP。
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

以下修订是 S3/S4 的防护设计及 S5–S7 的集成要求，**不是已实现的修复，也不另建一套 Gate**。第 6 节原 S0–S9 表保持原文；第 6.1 节将恢复场景映射到这些原 Gate。

#### 3.4.1 在原生 pin 执行点关闭 pin

本 Graph 不需要动态 pin，因此两个 pin hook 均采用 Fail Closed，而不是“发现后清空再继续”：

- **拟议唯一扩展点**：固定 `deepagents.middleware.skills.SkillsMiddleware` 的最小派生类，同名 `name="SkillsMiddleware"`；通过 `create_deep_agent` 现有按名称替换机制放入原 slot。只覆盖 `before_model` / `abefore_model`：非空或畸形 `pinned_skills` 立即拒绝，空 pin 返回无更新；不得调用父类 pin 实现、下载 pin 正文或生成 pin HumanMessage。
- `before_agent` / `abefore_agent` 的原生扫描解析、metadata 提示渲染、Skill 工具披露约束和其他非 pin 行为继续继承 SDK；原生 FilesystemMiddleware 的 `read_file` 不替换成自制读取工具。仍只允许三个固定路径、两次读取、六次 Reader 与原六工具，禁脚本/延迟工具扩权。
- 必须覆盖同步和异步 hook。单独新增一个排在原生 pin 前的 guard 不能作为修复，因为恢复可以跳过它；只在模型包装器读取 pin 字段同样不能作为修复。
- 实测最终堆栈中仅一个有效 Skills 原生派生实例、slot 名称与 hook 绑定正确；证明原生扫描与模型渲染实际被调用且没有额外有效实例/重复扫描。若锁定 SDK 无法满足原 S2 的原生唯一装配要求，继续 STOP，不以“功能相似”替代原 Gate。
- 尚未验证的契约：派生 hook 在所有恢复点是否保持绑定、LangGraph 编译是否选到正确同步/异步实现，以及 Aegra 工厂/复制后是否保留它们。源码可见的同名替换支持不能代替 SDK/FakeModel 实测；不 monkey-patch SDK、不复制整份 SkillsMiddleware、不升级版本。

#### 3.4.2 Skills Profile 的受控入口与 State 写入策略

只读快照保护内容；入口策略还必须保护“谁能改变执行状态”。候选为仅在独立 Skills Profile 注册的 **Aegra runtime factory + 显式受控 Graph facade + Profile 专用 auth hooks**；复用现有登录机制，不改 Aegra 依赖源码、正式 auth/Graph、P0、Reviewer 或其他 Profile。

本轮只读检查的 Aegra 0.10.8 源码事实：`services/graph_factory.py` 以服务器创建的 `ServerRuntime.access_context` 区分 `threads.create_run`、`threads.update`、`threads.read`、`assistants.read`；`api/threads.py` 的 State POST 除普通 `values` 更新，也支持 `values=null` + `as_node="__copy__"` 的派生 Checkpoint。`langgraph_service.py` 还会 `copy(update=...)` 注入 Checkpointer/Store。这些是拟议防护的接入候选，**尚非 HTTP 集成验证结果**。

1. Factory 仅信任服务端 runtime 的 access context；不信任客户端 config/context/metadata 中同名字段。`threads.update` 在任何写入前拒绝，包含 dict/list `values`、空值、`as_node`、`__copy__`、指定 checkpoint/namespace 的变体；不得返回裸图继续更新。只读 schema、State/History 请求可保留。HTTP 拒绝应有明确 4xx/错误契约；若固定 Aegra 无法用受支持的 Profile 级扩展实现，保持 BLOCKED，不能只接受 500 或绕过入口。
2. 新 Run 的客户端输入仅允许单条新的 Human 消息；拒绝整个含额外 State 字段的 payload，而非静默丢字段后运行。拒绝 `files`、metadata/pin/load-errors/disclosed-tools、Todo、预置 AI/Tool/System 消息和伪装的 pin 消息；批量消息、嵌套/别名形式也须同样校验。服务器 Checkpoint 内合法历史与 SDK 内部 Todo 更新不由此禁止。
3. Resume 仅接受服务器确认的同一 Skills Graph/Thread、当前根 namespace、当前 head Checkpoint；`input=None` 只在确有待续任务且完整 State 校验通过时执行。客户端 `Command(update=...)`、`goto`、自选 `as_node`/执行节点、任意 checkpoint namespace/ID、历史 time-travel、跨 Thread/Graph copy、fork/import/replay 和强制重置预算全部拒绝。暂停控制仅允许服务端白名单的静态暂停点，不能提交任意节点或中断参数。当前 Skills 无业务 HITL；未预期的动态 interrupt 和 `Command(resume=...)` 本轮默认拒绝，保留错误和历史，不伪造续跑。正式 HITL/Resume 不受此新 Profile 规则影响。
4. **拟议持久化方案**：复用本实验专属、初次启用时为空的 Aegra Postgres Checkpointer（S1 用 MemorySaver）；不增加第二套数据库或密钥服务。由 Host 在受控新 Thread 首次执行时写入私有 binding channel，包含服务器确认的 Graph/Thread/根 namespace、Graph 修订、三份快照清单、当前 Human 轮次及已提交调用/消息的完整性摘要。Resume 从服务器已提交 head 读取、核验任务位置与摘要，不从客户端 config/metadata 重新播种；没有 binding 的旧 Thread 不可“补签”后恢复。SDK hook 产生的合法状态如何在每次提交后更新摘要、错误/取消时何种 head 可续跑，须先以 S1 的完整提交时序证明；不采用客户端提供的摘要，不以 hash 本身认证来源。
   该方案的信任根是 **专属 Checkpointer + 全部客户端写路径已封闭 + Host 受控提交**，不是 channel 的名称或 `PrivateStateAttr`。Profile 专用 auth hooks 须校验 Thread create/update（含 metadata PATCH），拒绝客户端预置/变更保留的 Graph/版本/绑定字段；factory 另拒绝 State update。API key 的持有者也不能调用内部 State 写方法；既有正式 auth 不改。跨进程读取仍从同一受保护 Checkpointer 验证，Thread metadata 仅供显示/路由、不能认证 binding；单用户登录不等于 State 写入授权。
   所有 Run/SDK/HTTP 路径封闭和服务器绑定来源必须在 S1/S2 分别验证；读取接口不会赋予写权限。直接恶意修改数据库/进程内存不在此客户端威胁模型内，不声称防御；来源不明的数据库或导入历史不接受。若无法用固定 Aegra 的受支持 Profile 扩展封闭任一入口/提交时序，则该方案 BLOCKED/STOP，不以进程内缓存、可写 Thread metadata 或新基础设施补足。
5. 受控 facade 显式覆盖所有执行与状态修改方法；`copy`、`with_config`、Checkpointer/Store 注入和 schema/读取适配返回的对象都必须保留执行边界，不可用通用 `__getattr__` 把写入口或裸图暴露出去。直接/bulk update 方法拒绝；支持的 invoke/stream/batch 逐入口执行相同验证，不支持的同步/批量/事件版本入口须在副作用前明确拒绝，不能默认委托。Aegra 入队、后台 worker、等待/流式/无 Thread Run 的实际调用也不能绕过。
6. 通过隔离 Profile 的 HTTP/SDK 负测证明 facade 和 factory 在真实调度/注入后仍有效；复制丢包装器、注入失败后回退裸图或静默无持久化均为 FAIL。若需要修改公共 Aegra/正式链路才能继续，先 STOP，不能扩大本修订授权。

#### 3.4.3 模型、工具与 Checkpoint 的最后防线

即使入口已拒绝客户端 State 修改，也要在实际模型 handler 和每个工具 handler 前独立校验。该检查不能仅依赖新 Run 的 `before_agent` 是否执行。

- 从可信快照建立 canonical metadata，校验三项的完整内容、路径和来源；不只比名称。pin 必须为空且类型合法；拒绝包含 include-tools、伪造 load-errors/disclosure、pin 来源消息或未知历史结构的恢复状态。原生 metadata 扫描仍必须真实执行，不能由 Host 直接把三份正文塞入 Prompt。
- 对历史已带 `lc_source=pinned_skill` 或等价强制加载内容的 Checkpoint，拒绝模型和工具执行；**只清空 pin 字段不够**。客户端删除/伪造该标记也不能让历史变可信：能否恢复由服务端 Checkpoint 来源和受控变更链决定，不能单凭消息标记或正文 hash 放行。
- 校验当前 Human 轮次与唯一 AI/Tool ID 配对；Skill 载入必须有服务端实际原生 `read_file` 轨迹，指南不能被当作 Reader 当前证据。恢复已有合法轨迹可以保留，但不得通过伪造历史 AI/Tool、增加 Human、客户端 config 或 copy 重置读取/Reader/Todo/决策预算。
- 同一 Thread 的状态核验、选 head 与执行须受同一服务端互斥/调度约束。排队到执行之间再次校验；同 Thread 并发 Run、运行中 State 写入、取消与新 Run 竞态不能制造检查后覆盖或重复隐藏加载。不同 Thread 的固定技能字节可相同，消息、Todo、预算和执行身份不得混用。
- 如实现使用私有执行上下文，须由 Host 每次实际执行建立，不能从请求/State/config/Checkpoint 恢复；异常、取消和流关闭后清理。跨进程正常恢复依据已验证的服务端 Checkpoint 与当前固定快照重新校验，不能恢复私有授权或把旧 pin 当加载许可。
- 拒绝时保留可诊断错误和原始历史，不通过删除坏消息、伪造 `read_file` 成功、清零预算或重新创建同名 Thread 来“修好”。缺少受信来源/版本的旧 Skills Checkpoint 拒绝执行，允许用户另开新 Thread；不迁移/改写正式或其他 Graph 的旧 Checkpoint。

#### 3.4.4 恢复路径与预期行为

所有“拒绝”均要求：验证失败后 **模型 handler=0、Reader/Todo/read_file handler=0、pin 注入=0**，固定快照与虚拟文件无非法副作用。元信息的受控原生扫描不算正文进入模型；必须分别计数。拒绝 HTTP State 修改还须证明没有创建新 Checkpoint 或改变 head。成功 Resume 必须保留实际调用配对和本 Human 轮次已用预算，不能仅验证最终中文输出。

| 路径 | 防护与允许行为 | 必须覆盖的正反例；映射原 Gate |
| --- | --- | --- |
| 新 Thread / 同 Thread 新 Human Run | 严格消息输入，原生 metadata 扫描，Host 建立新轮次；客户端 State 全拒绝 | 三故障按需 read_file、问候零读取；空/畸形/额外字段、伪造 AI/Tool/pin 拒绝；S2/S3/S4 |
| 静态 interrupt before/after | 在实际 pin hook 禁 pin；模型/工具执行点重新校验，不依赖前置 hook 重跑 | 枚举实际图中 before-agent、所有 before-model（尤其 pin）、model、tool、after-model/after-agent 节点的前后暂停点；干净恢复成功，篡改后零执行；S3/S4 |
| `input=None` / SDK Command / config | 仅允许经过核验的当前 head 的无更新续跑；本轮拒绝 Command 更新/跳转/业务 resume | None 正例；update/goto/resume、别名 checkpoint 参数、伪造服务端 access_context/版本拒绝；S3/S4 |
| pin 消费后的历史恢复 | 禁 pin hook + 验证历史来源/结构；空 pin 不代表安全 | 保留第 1.1 节精确攻击；再测 pin 已清空但三份 Human 正文已持久化、伪造/去掉 marker、伪造 read_file 回执；S3/S4 |
| 工具前、工具后、pending writes | 先验证恢复状态，再执行原生工具，保留预算/配对；无效状态不发工具请求 | 第2次读取后恢复，第3次拒绝；并行读取、重复ID、部分完成/错误回执、预算耗尽；拒绝凭 pending 状态补造加载；S3/S4 |
| HTTP State / Thread metadata / copy / fork / time-travel | 独立 factory + auth hooks 拒绝修改、伪造绑定与派生；GET State/History 只读保留 | State POST 的 dict/list/空值/`as_node=__copy__`/checkpoint参数组合；Thread创建/metadata PATCH伪造保留字段；拒绝前后 head 与历史一致；S3/S5/S7 |
| Cancel / timeout / 异常后恢复 | 仅从服务端已提交 head 核验续跑；丢弃无效私有执行上下文，保留已用预算 | 在扫描、pin、模型、Reader、read_file 各位置取消/异常；无后台残留写入，干净合法续跑成功；S3/S4/S5 |
| SSE 断线重连 / Web 刷新 | 重连只读取同 Run 事件，不隐式新建 Run 或再加载技能；真实取消单独处理 | Last-Event-ID 无不当重放；on_disconnect=continue 与 cancel 分开；Timeline/Todo 与 Checkpoint 一致；S5/S6 |
| Aegra 进程/worker 重启 | 同修订/同快照、合法 head 可重新校验恢复；无效来源拒绝 | 干净恢复正例；缺版本、变更快照、旧 pin/伪造历史拒绝；不能靠进程内缓存证明跨进程安全；S3/S5/S7 |
| 同 Thread 并发 / 不同 Thread | 核验到执行互斥；无状态覆盖竞态和跨 Thread 私有数据 | 并行Run、运行中State更新/取消竞态；双Thread独立消息/Todo/预算，跨Thread/Graph checkpoint拒绝；S3/S5/S7 |
| Graph/facade 复制与入口分派 | factory、copy/with_config、Checkpointer 注入后边界仍在 | 原生唯一装配；invoke/stream/events/batch每种入口的允许或明确拒绝；等待/排队/后台/无ThreadRun无裸图回退；S2/S3/S5/S7 |
| 旧 Thread / 其他 Graph / Profile | 不自动迁移，不接受复制的可信标记；不改现有 Graph | 只读查看旧历史；旧Skills恢复拒绝并提示新Thread；正式/P0/Reviewer/Reader/HITL/Memory回归；S3/S7 |

S1 先以真实装配与 MemorySaver 逐暂停点枚举并验证受控入口；不得假定只列出的两三个节点足够。S2 再以隔离 Aegra/Mock、Postgres Checkpointer、后台 worker 和 Web 运行上述对应项，验证实际 HTTP 路由、重启与竞态。任何未枚举的新执行/写入入口默认拒绝；若实际 Aegra 依赖该入口却不能安全支持，标 BLOCKED 并 STOP，不能只关闭测试场景。

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

本修订追加明确停止点：pin 仍可执行或绕过 read_file 强制注入；任何 Resume/State/copy/worker 路径剥掉边界；拒绝前已有模型/工具执行、非法文件写入或 HTTP State 修改；缺少服务端来源而借用客户端 hash/标记；为使正例通过而重置预算、关闭必要恢复测试或降级原 Gate。保留旧 `resume-pin` FAIL，直到经批准的新装配逐路径重验；本纯文档修订不解除 S1 STOP。

## 5. 任务分阶段

| 阶段 | 实施范围 | 交付物 | 进入下一阶段 |
| --- | --- | --- | --- |
| **Planning（本 PR）** | 只建 Issue/设计文件；不运行或提交业务代码 | 纯文档 Planning PR、Refs #75 | 人工审阅并合入 main |
| **S1：官方 API 与安全加载 Spike** | 锁定 0.7.28、三个 `SKILL.md`、只读 Backend、SDK SkillsMiddleware 装配、渐进读取、白名单与 State 负测；FakeModel + 合成 Fixture | 独立 PoC 测试、精确工具清单、负测报告 | **S0–S4 全 PASS** |
| **S2：隔离 Aegra/Web** | 新 Graph/entry/启动 Profile、现有 Timeline/Todo、Checkpoint 和 Thread/取消/恢复；仅 Mock，无真 K8s | Web Demo / 集成证据 / 使用说明 | **S5–S7 PASS** |
| **S3：对照/工程交付** | 6–9 个合成用例，FakeModel A/B、回归 Ruff/pytest/Web/CI、独立 AO Review、中文 Gate | Implementation PR（Refs #75）、总结与回退 | **S8–S9 PASS** |

最短路径：S1 在同一实现 PR 中分 commits 也可，但失败需保留证据、STOP，不得完成“文档 PASS”后直接跳 S2。真实模型测试由单独授权的可选计划执行，绝不作为已默认批准的预算。

本次重启顺序：本设计修订 **人工审阅并合并** → 重新 fetch/main/Issue → S1 保留旧反例并验证原生 pin 扩展、入口与全部暂停点 → S0–S4 全 PASS → S2 的 HTTP/持久化/worker/Web 恢复验收，S5–S7 全 PASS → S3。源码阅读、Planning PR 的 CI 或 AO 审阅都不等于实现 Gate PASS；本轮不得进行上述后续实现或模型/Kubernetes 调用。

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

### 6.1 原 Gate 的恢复验收补充与证据要求

上表 **S0–S9 的 ID、原文和阶段门槛不变**。第 3.4.4 节矩阵是 S2/S3/S4/S5/S6/S7 的具体测试展开，不能代替或缩减任何原场景。S0 还须记录本修订人工审阅合并的 PR/SHA；S9 交付时附完整展开项及其所属 Gate。

- **S2/S3**：记录实际实例类型、名称、hook绑定、扫描次数、模型首次输入、每次正文进入模型的来源；保留旧反例统计 `1模型/3pin/0read_file` 与失败断言。修订装配的同一攻击须被拒绝，模型/工具/pin注入均为0；正常渐进加载正例不得退化。
- **S3/S4**：逐节点前/后暂停点 × 同步/异步实际入口 × State/消息/config/Command 注入，包含完整复制、只改 pin、清空 pin 保留已注入消息、marker伪造/移除、metadata同名改描述/路径与多次恢复。分别记录执行/拒绝位置、工具ID、读取及Reader/Todo/决策计数、旧/新head与文件差异；两次读取预算跨取消/恢复不能重置。
- **S5/S6/S7**：离线通过后再做真实隔离 Mock HTTP/SSE、数据库持久化、worker/进程重启、Aegra copy/注入和并发。覆盖表中每个对应项，拒绝响应与State不变证据俱全；合法Resume、刷新和重连必须有正例，不能通过拒绝所有恢复来声称通过。浏览器自动化与真人验收分开，未跑者明确 NOT RUN。
- 每项采用 PASS / FAIL / NOT RUN / BLOCKED / UNKNOWN，附命令、Python/SDK/Aegra版本、提交与快照版本、暂停/恢复节点、实际计数和适用范围。旧负例characterization的“符合预期”不代表安全PASS；只有新装配的禁止绕过断言通过才可计入S3/S4。本次修订的实现与新安全验收全部 **NOT RUN**，当前 **S1 STOP、S3/S4 FAIL** 不变。

## 7. 人工审阅要点与社区对照

- Skills 不是 Prompt 中临时插入三段文本；要用 SDK 原生 `SkillsMiddleware` + SKILL.md + read_file **动态按需读取**。
- Skill 只是开发者维护的指导文件，与实时 MCP 证据、用户授权、Tool 权限各自独立；不出现“通过 SKILL.md 获取读取 Kubernetes 新 API 的权限”。
- 固定 Skill 来源是否足以防 Aegra 用户可写 `files` 或 metadata 混淆；不得把只读内存 Snapshot 的实现复杂化成泛用文件服务。
- 不新增冗余 Agent，避免在 #69/#72 未完成时产生并行工作树冲突。
- 2026-10-22 的 SDK 与官方资料可能持续变化：执行前核对锁定 SDK 源码，所有推测性行为必须用 FakeModel 真实 assembled 实例与 State/Run 验证。

## 8. AO 交接（只在 Planning PR 合并 main 后有效）

- 仓库 `Vc-great/kube-triage-agent`，Issue **#75**。
- 设计 `docs/plans/issue-75-kubernetes-diagnosis-skills.md`（需先在 `origin/main` 确认存在）。
- #76 已人工审阅合并；本次 pin/Resume 修订须另经人工审阅并合入 main 后才可继续。保留第 1.1 节旧失败，先验证第 3.4.1–3.4.4 节和第 6.1 节；不得把纯文档 PR 的通过当成修复完成。
- 先 S1 / S0–S4，全部 PASS 方进入 S2/S3；只实现已批准阶段。
- STOP：原生 Skills 不成立、无法安全保护打包内容、越权工具、真实集群/未知付费模型出站、正式/P0 回归、未知 SDK API。
- 提交独立 Implementation PR（Refs #75）和中文 Gate 报告；未经用户批准不合并、不关闭 Issue。
