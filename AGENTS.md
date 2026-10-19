# AI 开发代理协作约定（AGENTS.md）

适用范围：整个仓库。本文只保存长期有效的约束；单个任务的需求、详细设计、阶段划分与验收 Gate 以对应 GitHub Issue 和经审阅的计划为准。统一工作流参见 [docs/agent-workflow.md](docs/agent-workflow.md)，计划规则参见 [docs/plans/README.md](docs/plans/README.md)。

## 1. 首次读取与事实核对

- 默认使用中文沟通、撰写文档与 PR 描述；代码命名、SDK API 和现有项目约定保持原样。
- 在实施前执行 `git fetch origin`，记录当前 `origin/main` SHA；检查目标 Issue、关联 PR、正在进行的工作、受影响代码及依赖版本。不要把历史计划中的 SHA、端点、Graph/SDK 结构当成最新事实。
- 只按需阅读文档：`README.md`、`docs/architecture.md`、对应模块和 Issue 指向的计划。不要无差别读取全部历史 `docs/phase*` 或其他 Issue 文档。
- 明确区分「已实现」「规划中」「未经验证」「历史记录」；如果 Issue、计划和当前代码矛盾，说明冲突并停止有风险的实现，不能自行降低目标或安全 Gate。
- 不重复实现已经合入 `main` 的能力，不覆盖别人的工作树或未提交修改。

## 2. 任务分级与输入

- 小任务：范围清晰的 Bug/文案/局部测试修改，Issue 足够时无需额外计划文件。
- 中任务：涉及多个模块、协议或可验证的行为变更，优先在 `docs/plans/issue-<编号>-<主题>.md` 存放单份设计与验收计划。
- 大任务：多阶段、多 PR、跨架构/安全边界、迁移或成本高的实验，可将 Spec/Design/Tasks 拆分；一个位置作为验收标准的权威来源，其他位置只链接，避免双份维护。
- 对中大型任务，先创建仅包含计划文档的 Planning PR；经人工审阅并合并到 `main` 后再启动 AO/Codex 实施。若规划 PR 未合并，新 Worker 不得假设该文件存在于 `main`。
- AO 任务提示词应简短，只提供 Issue 编号、经合并的文件路径、当前阶段与停止边界；不要把整份设计复制进 AO。实施前必须打开并核对文档。
- 文档中的计划不是任务完成证明；只能以真实代码、测试、CI 和 PR 证据判断完成情况。

## 3. 本项目不变量

- 这是单用户、面向学习/面试的 Kubernetes 诊断 Demo，而不是生产 AIOps；正式链路必须遵守当前代码中的授权、白名单和 Fail Closed 约束。
- 原生 Reader MCP 的 Namespace、工具/参数校验和只读权限不可被 Prompt、实验 Graph 或新中间件绕过。
- Repair、审批、`interrupt/Resume`、旧 Checkpoint/Thread 与历史证据都属于敏感行为边界；不得把 Mock 成功或历史模拟审批解释为真实集群写入授权。
- 未经任务中明确批准，不连接真实集群做写操作，不自行扩大 RBAC，不自动做真实 Repair；真实模型付费调用、对外传输敏感数据或改变既有部署也应先确认范围和授权。
- 不输出、提交、记录或复制 `.env`、Token、kubeconfig、真实日志敏感信息、私有评测轨迹；如需测试使用合成数据和脱敏证据。
- 不擅自操作稳定环境或其他项目的 Compose/容器/卷/端口。需运行测试环境时，先检查资源归属，用独立 Worktree、独立项目名、数据卷与端口；仅清理本任务创建的资源。

## 4. 实施、验收与 PR

- 优先最小变更，复用现有 Aegra / LangGraph / MCP / Web 代码与文档；不进行无关重构、不凭空引入额外平台。
- 按批准阶段逐步实现；明确 Gate（例如 PASS / FAIL / NOT RUN / BLOCKED）。每个 PASS 要有命令、版本/环境、输出或可核对的证据；`NOT RUN`、`BLOCKED`、`UNKNOWN` 不得标记为 PASS。
- Python 验证以仓库当前锁文件和环境为准，常见命令：在 `server/` 执行 `uv run --frozen ruff check src tests`、`uv run --frozen pytest -q`。前端在 `apps/web/` 执行 `pnpm lint`、`pnpm build`；按改动范围选择测试，不为纯文档 PR 伪称执行过代码测试。
- 提交前检查 `git diff --check`、文档链接、范围差异，以及是否误纳入密钥/私有数据。
- Planning PR 仅改规划文档，使用 `Refs #<编号>`，不关闭功能 Issue。Implementation PR 附范围、设计偏差、测试证据与剩余风险；多阶段任务仅在最终阶段满足全部 Gate 后才考虑 `Closes #<编号>`。
- 是否设为 Draft、Ready for Review 或合并，服从目标任务及既有自动化门禁；没有明确授权不自行合并、放宽 Gate 或关闭 Issue。代码合并后更新现状文档，并将历史计划标记为已完成或归档。

## 5. 冲突与停止

优先依据用户本次明确要求、GitHub Issue 确认的范围/验收 Gate、已合并并获审阅的计划和本文件的通用操作约定处理任务。若安全/授权条件冲突、计划文档缺失、关键 API 无法验证、基线已过时或需要扩大执行范围：先报告差异、最小替代方案及证据，再等明确决策；不要静默绕过。