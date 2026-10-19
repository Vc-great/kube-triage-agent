# 网页 ChatGPT → GitHub → AO → Codex：轻量 SDD 开发工作流 v1

> 状态：本文件是仓库级**协作流程**，不是某个功能已经完成的证明。批准/合并到 `main` 后作为后续任务的默认流程；历史任务不被自动追溯要求重做。
>
> 适用项目：`kube-triage-agent`。长期代理规则见 [AGENTS.md](../AGENTS.md)；计划文档与模板见 [plans/README.md](plans/README.md) 和 [plans/TEMPLATE.md](plans/TEMPLATE.md)。

## 1. 背景与目标

项目已通过 GitHub Issue、分阶段 Draft PR、独立 Worktree、真实/合成验收和较多 `docs/` 文档组织开发。AO 的新任务入口存在约 16 KiB 文本上限，长中文提示词不适合作为需求的唯一载体。将一次性执行指令与可版本化、可审阅的项目文档分离。

目标：
1. 网页 ChatGPT 负责审阅现状、提出设计，并通过**独立文档 PR**将方案写入仓库。
2. GitHub Issue 保存问题背景、需求边界、当前状态和验收标准权威入口；仓库 Markdown 保存适用于多轮工作的详细设计、实施计划与验收矩阵。
3. AO 使用短提示词指定 Issue、已合并文件路径、阶段和停止条件；Codex Worker 按需读取文件后执行。
4. 保持基线可追踪、计划可变更、实施可验收；严格区分计划、代码现状、测试证据和实际部署状态。
5. 复用已有 GitHub/CI/AO 能力，不安装 Spec Kit/OpenSpec、不引入数据库或专用工作流服务。

非目标：自动修改所有历史 Issue；替换现有评测与运行工具；自动部署到 dev01/真实集群；自动扩大权限、越过审批或让文档直接触发代码执行。

## 2. 文档职责（避免重复真相）

| 载体 | 保存什么 | 不保存什么 |
| --- | --- | --- |
| GitHub Issue | 背景、目标、In/Out Scope、不可变约束、验收 Gate 唯一来源或索引、讨论与完成状态 | 成百上千行重复的实施日志 |
| `docs/plans/issue-<编号>-<主题>.md` | 中/大任务的技术设计、选型与依据、阶段、依赖、回退、逐条 Gate、执行指令 | 密钥、未经验证的「已完成」结论 |
| `AGENTS.md` | 所有任务通用的项目约定、安全/验收规则与必读入口 | 具体 Issue 的长方案、历史流水账 |
| `docs/architecture.md` 等当前状态文档 | **已合并且经核对**的系统实现和当前运行方式 | 尚未批准或未合并的新设计 |
| PR / CI / 验收报告 | 实际提交 SHA、命令、环境、PASS/FAIL/NOT RUN、发现与偏差 | 用计划预计结果冒充实测 |

验收标准必须只有一个**权威版本**：默认在 Issue；若大型任务将完整矩阵移至计划，则 Issue 明确链接该计划和版本，并不维护第二套可能漂移的矩阵。修改 Gate 时同步更新入口且需重新审阅，不允许 Implementation Worker 自行降低门槛。当前代码/运行证据用于验证“实际上有什么”，不因文档声称而自动变真。

## 3. 任务分级

- **S / 小任务**：影响局部，范围和验收清晰，无架构/安全/部署争议。仅用 Issue，直接进入实现 PR；不强制额外 Markdown 和 Planning PR。
- **M / 中任务**：跨模块、有 API/协议变更、多个验收场景或方案权衡。Issue + `docs/plans/` 单份 Markdown；先 Planning PR 再 Implementation PR。
- **L / 大任务**：多个独立 Gate/PR、变更安全边界、A/B 评估、数据迁移或高风险实验。先设计，按需要拆分 `spec.md`、`design.md`、`tasks.md`，但**不强制**三件套；每一阶段使用单独实施 PR 和停止 Gate。

任何规模遇到真实集群写入、权限扩大、秘密/个人数据外传、付费模型大批量调用或稳定环境破坏性操作，都不能因为属于“小任务”而省略授权。

## 4. 状态机与角色

~~~text
Issue 建立/更新（任务范围与 Gate）
  ↓
ChatGPT 只读调研：fetch main、Issue、关联 PR、实际代码、依赖
  ↓
[中/大任务] 设计 Markdown → 纯文档 Planning PR
  ↓                    ↘ 审阅拒绝/新事实 → 修订方案
人工审阅通过 → Planning PR 合并 main
  ↓
AO 短提示词（Issue + main 中真实存在的计划路径 + 当前阶段）
  ↓
Codex：独立 Worktree → 核对实时 main → 读取计划 → 实施/测试
  ↓
Implementation PR（关联 Issue，逐项 Gate + 实测）
  ↓
独立评审 / CI / 必要的人工验收
  ├─ FAIL / BLOCKED / 需改设计 → 修订并重新验收
  └─ PASS 且获授权 → 合并 → 更新当前架构/归档计划
~~~

职责：
- **用户**：批准范围、关键设计和外部权限；最终验收必须由谁执行，以任务要求为准。
- **网页 ChatGPT / Planner**：阅读目标仓库与既有 Issue/PR，识别重复工作；创建设计分支、规划文档、Planning PR；**不在规划 PR 中偷偷实施业务代码**。
- **AO**：创建 Worker、限定执行阶段、编排审查；短提示词不是需求的唯一真相。
- **Codex Worker**：基于新的 `origin/main` 在独立 Worktree 实施；用代码与测试验证，不能因为读过设计就视为完成；出现高风险偏差要停止并反馈。
- **Reviewer/CI**：独立核对变更范围、设计偏差、CI 与 Gate 证据。自动评审不替代明确要求的真人批准。

## 5. 从规划到实现的交接契约

### 5.1 Planning PR

1. 读取实际 `main`、受影响源文件、当前锁定依赖、Issue 和关联 PR；在文档中区分已经实现、尚未实现与假设。
2. 按 [模板](plans/TEMPLATE.md)写清目标、非目标、变更范围、设计、替代方案、风险、执行阶段、验收 Gate 和停止条件。
3. 仅提交 Markdown/导航类更改，以 `docs/sdd/issue-<N>` 之类的独立分支创建 **Planning PR**，说明“仅规划，不修改业务代码”，关联 `Refs #N` 而不是 `Closes #N`。
4. 人工审阅后合并 `main`，必要时在 Issue 添加稳定文档路径和规划 PR 链接。
5. **未合并前不启动依赖该设计的 AO 实施 Worker。** 不依赖某个本地 Worktree 中未提交的文件，也不指示 Worker 读取只有规划分支才有的路径。

例外：某一实施 Worker 可以被明确指定使用已固定 SHA/分支的规划文档，但必须显式将版本写进任务、能访问该 ref，并承认该方案还未进入 `main`；默认流程不采用此例外。

### 5.2 Implementation PR

- 每次启动先 `git fetch origin`、记录实施时 `origin/main` SHA、关联 PR/Issue 状态及实际 SDK/API；检查规划文档是否存在且为预期版本。
- 从目标 Gate 开始，列出「已完成」「未完成」「有争议」与代码位置，不重复开发历史阶段。
- 多阶段任务只实现当前获准阶段；每阶段单独 PR，通过明确 Gate 才能进入下一阶段。不要用 Phase A PASS 推断 Phase B PASS。
- PR 必须提供：改动摘要、范围/偏差、提交 SHA、测试命令与环境、每个 Gate 的证据等级、未运行项目与风险、回滚方式。
- 非最后阶段以 `Refs #N` 关联 Issue。只有最后阶段确实满足关闭条件时才使用 `Closes #N`；GitHub 自动关单发生在合并默认分支时，不等于“合并后 CI 已完成”。若需要 CI 完成后才关单，应另行设计 Actions/关闭器。
- PR 何时从 Draft 转 Ready、由谁合并，遵守具体任务已有的 AO 审查门禁。未明确授权时默认保持待审、不自动合并。

### 5.3 设计偏差、失败与继续执行

- **可自行解决**：不改变验收标准的小型兼容修复、实现路径微调；在 PR 解释与记录原因。
- **必须重新评审**：用户可见行为/安全边界改变、删减 Gate、引入新基础设施、权限变化、迁移/数据删除、授权成本增加、无法实现的 SDK 假设。
- 失败保留为 `FAIL`、`NOT RUN` 或 `BLOCKED`；不得修改历史失败报告制造成功。必要时创建设计修订 PR，合并后用新版本重新实施。
- 合并后更新与本次实际变化有关的当前状态文档；历史计划保留并标明 `Completed/Archived`，作为设计决策证据，不应继续作为现行系统说明。

## 6. 验收证据格式

一个 Gate 至少包含：稳定 ID、测试对象/环境、操作或命令、通过判定、结果状态、证据位置、限制/剩余风险。推荐结果词：`PASS` / `FAIL` / `NOT RUN` / `BLOCKED` / `UNKNOWN`。没有真实 Provider、真实 Kubernetes、人工 Web 测试时，明确 `NOT RUN`，不要依据 FakeModel/Mock 结果外推真实环境。

本项目建议优先选择离线 FakeModel/Mock 测试；执行 `ruff`、`pytest`、`pnpm lint`、`pnpm build` 需按本次改动的实际范围选择并报告。真实 Reader/Repair、HITL、Checkpoint、SSE、Memory、历史评测不变量按目标 Issue 与代码再次核对。不要启动/清理无关 Compose、端口、数据卷；任何真正写集群的操作必须另行获批。

## 7. 可复用的短指令

**网页 ChatGPT 规划指令：**

~~~text
请为 Vc-great/kube-triage-agent Issue #<N> 制定实施方案。
先核对最新 main、相关代码/依赖、已有 PR 与项目规范。
中/大型任务在 docs/plans/ 创建 Markdown，包含范围、设计、阶段、风险和 Gate。
提交纯文档 Planning PR（Refs #<N>），不修改业务代码，不关闭 Issue，不合并 PR。
~~~

**AO/Codex 执行指令（计划已合入 main）：**

~~~text
实施 Vc-great/kube-triage-agent Issue #<N> 的 <当前阶段>。
先 fetch origin/main，在独立 Worktree 核对 AGENTS.md、Issue 与 docs/plans/<实际路径>。
只实施当前阶段，遵守已有安全/验收 Gate；缺计划、证据不足或需扩大范围时停止。
完成后跑必要测试，提交独立 PR（Refs #<N>），报告每项 PASS/FAIL/NOT RUN/BLOCKED。
非最终阶段不关闭 Issue；未经授权不自动合并。
~~~

这些是**模板**，`<实际路径>`、`<当前阶段>` 等占位符必须替换为仓库中已存在且 Worker 可访问的值；没有计划文件的小任务不要强制引用。

## 8. 流程自身的验收与采用方式

| ID | 验收点 | 通过条件 |
| --- | --- | --- |
| WF-01 | 入口 | 根目录 `AGENTS.md` 与 README 导航均能指向本文件和计划模板 |
| WF-02 | 单一真相 | Issue 与模板明确 Gate 来源，禁止 Issue/Markdown 双份互相漂移 |
| WF-03 | 分支可见性 | Planning PR 合入 `main` 后，AO 从新 Worktree 能读取计划 |
| WF-04 | 阶段隔离 | 非最终 Gate/PR 不擅自进入下一阶段，也不关闭功能 Issue |
| WF-05 | 风险保护 | 保留 Reader/Repair/Mock/Real、密钥、生产资源归属和人工授权要求 |
| WF-06 | 可核对结果 | 每个实施 PR 有实际命令、环境、Gate 结果与缺口说明 |
| WF-07 | 纯文档试运行 | 本次规范 PR 不修改源码/依赖/CI，不宣称未跑过的程序测试 |

采用策略：本 PR 只落地规则和模板；**不自动迁移 #41 或其他进行中的任务**。下一次新中/大任务优先试运行一次 Planning PR → 合并 → AO 短提示词 → Implementation PR → 验收，然后根据实际成本迭代流程。