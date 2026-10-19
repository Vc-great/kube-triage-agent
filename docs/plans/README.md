# 开发计划索引与存放规范

本目录保存**计划中或曾经计划过的变更设计**；不代表功能已实现。长期协作规则参见 [AGENTS.md](../../AGENTS.md)，流程见 [轻量 SDD 工作流](../agent-workflow.md)，首次编写请从 [TEMPLATE.md](TEMPLATE.md) 复制。

## 何时需要建计划文件？

| 类型 | 默认资料 | 是否需要 Planning PR |
| --- | --- | --- |
| S：单点 Bug、配置/文字修复 | GitHub Issue + 实施 PR | 否 |
| M：跨模块、协议、功能切换、可验证行为设计 | Issue + 本目录单份 Markdown | 是 |
| L：多阶段、多 PR、架构/安全/迁移/实验 | Issue + 本目录一份或拆分 Spec/Design/Tasks | 是，阶段验收 |

没有明确设计收益时，不为文档数量而文档化。禁止把历史任务重新全部搬入本目录。

## 命名与链接

- 常用格式：`issue-<编号>-<slug>.md`，例如 `issue-41-deep-agents.md`（**示例路径；目前并不表示已创建**）。
- 如果任务较大，可建立 `issue-<编号>-<slug>/`，下设 `spec.md`、`design.md`、`tasks.md`；不要同时把相同 Gate 完整复制在 Issue 和多个文件里。
- 文档开头必须包含：关联 Issue URL、状态、规划 PR、实施阶段、是否已批准、基线与适用版本。
- Issue 和规划 PR 互相链接；实施 PR 必须引用最终可读取的 `main` 中已批准文件，必要时给出具体提交 SHA。
- 避免把本地绝对路径（尤其是个人工作树）当作唯一引用；仓库相对路径可由 AO/Codex Worker 读取。

## 文档状态

`Draft` → `Proposed`（Planning PR）→ `Approved`（规划 PR 合入 `main`）→ `Implementing` → `Completed` / `Archived`。

- `Approved` 只表示设计被接受，**不是功能已经实现**。
- `Completed` 需对应最终实施 PR 和实际验收证据；`Archived` 是历史状态，不能被当作最新架构。
- 方案更新时记录“为什么变更/影响哪些 Gate/审批 PR”。未合并的改动不自动获得执行授权。
- 计划完成后保留文档，当前架构/部署说明应同步更新到 `docs/architecture.md` 等真实状态文档，避免规划与现状混淆。

## 写作与审查清单

- [ ] 阅读最新 `origin/main`、目标 Issue、关联 PR、真实代码与依赖版本；不照抄过时 SHA。
- [ ] 清楚区分当前能力、拟新增能力和未验证假设，写清 In/Out Scope。
- [ ] 明确一个验收标准权威来源，标注阶段、Gate ID、测试方法、停止条件。
- [ ] 解释安全/权限/付费模型/真实 K8s 边界、回滚及需要人工授权的事项。
- [ ] Planning PR 只改文档，不提前关闭 Issue；合入主线之后 AO 才按路径读取。
- [ ] 最终实施 PR 明确 PASS / FAIL / NOT RUN / BLOCKED 与证据，必要时由人验收。

## 参考

既有 Issue #41（Deep Agents）已经在 [GitHub Issue](https://github.com/Vc-great/kube-triage-agent/issues/41) 记录了 Phase A/B 与 Gate。是否将其详细实施设计迁入本目录，需要单独规划，**本次工作流规范不触碰该 Issue 的执行范围或已提交证据**。