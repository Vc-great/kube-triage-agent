---
name: submit-pr
description: 用于开发交付工作流。当完成代码或文档任务、需要提交/更新 GitHub PR、检查 CI、自动合并或关联 Issue 时使用；符合验证门禁就直接 Squash Merge，只有 Issue 真正完成才使用 Closes。
---

# submit-pr — kube-triage-agent 单人 Demo PR 交付

## 目标与默认授权

将「完成代码 → 核对变更与证据 → Draft PR → CI → 自动合并 → 回查 Issue」作为一次任务执行。**本项目是单用户面试 Demo，不要求额外的独立 AI Review，也不必为正常 PR 合并再次征求人工确认。** 当下面的自动合并门禁全部成立，直接合并到 `main`；如果有任何门禁失败，保持 Draft PR，报告阻断原因，不编造通过结果。

此授权**仅适用于本仓库内已经完成的开发任务的 GitHub PR 操作**。不授权真实 Kubernetes 写操作、调整 RBAC/签发 Token、清理其他 Worktree/Compose/数据卷、输出秘密，或修改历史验收结论。若当前环境有更高优先级的权限或执行限制，仍须遵守。

## 仓库约定（执行前核对实时内容）

- 仓库：`Vc-great/kube-triage-agent`；默认目标分支：`main`，**每次以远端实际信息复核**。
- 主要 CI：`.github/workflows/ci.yml`，截至 2026-10-15 为 `python` / `web` / `compose` 三项；如实时 Workflow 已改变，按真实配置执行，但不可接受 CI 被本次改动意外绕过。
- Python：`server/`，`uv`、`ruff`、`pytest`；Web：`apps/web/`，`pnpm lint`、`pnpm build`；Compose：`infra/`，只允许 `config --quiet` 等无副作用静态校验。
- 严格区分 Fake Model、Mock MCP、Real LLM、Real Kubernetes 的验证等级。CI 通过**不等于**真实集群 E2E 通过。
- Issue #11/#13 等可能仍有 FAIL/BLOCKED/NOT RUN；合并部分工作可以，不能自动把未完成 Issue 关闭。

## 流程

### 1. 确定本次工作范围，不干扰其他任务

1. 在当前任务的 Worktree 内操作；执行 `git status --short --branch`、`git remote -v`、`git fetch origin main`、`git branch --show-current`、`gh auth status`，检查远端默认分支和仓库地址。
2. 只处理本次任务关联的变更；若在 `main` 上、有不明来源的修改、目标仓库不匹配、没有可交付 Diff、存在 Merge 冲突，**停止**，不要强推、不要重置、不要改其他 Worktree。
3. 通过 `git diff --check`、`git diff --stat origin/main...HEAD`、`git log --format='%h %s' origin/main..HEAD` 以及未提交变更检查实际范围。若尚未提交，只暂存本任务明确涉及的文件；不要 `git add -A` 吞入秘密、私有结果或其他工作。
4. 检查 `.env`、`.local/`、kubeconfig、Token、Key、原始评测 Trace、个人地址/账号信息是否误入提交。发现任何秘密或越界文件立即停止；不要在 PR 中粘贴原文。
5. 核对 Issue 原文、相关 PR、实际验收项、历史 FAIL/BLOCKED/NOT RUN。不要因为分支名或 PR 标题出现 `#数字` 就推断全部完成。

### 2. 以最低成本执行与变更相称的测试

- 一律运行：`git diff --check`；阅读完整变更、核对 Python/Web/Compose/文档影响范围；本地检查失败不得声称 PASS。
- Python 变化：进入 `server/`，优先执行相关 `uv run --frozen pytest -q <测试路径>` 和 `uv run --frozen ruff check <相关路径>`；若依赖未安装，可先 `uv sync --frozen --python 3.13`。CI 最终会运行全套。
- Web 变化：进入 `apps/web/`，可执行 `pnpm lint` / `pnpm build`；如无依赖，可按 lockfile 安装，不更新依赖版本来凑通过。
- Compose / YAML 变化：只使用 `docker compose ... config --quiet` 等**静态验证**，独立项目名；不要启动、销毁或清理正在运行的服务。
- 纯文档/Skill：核验路径、frontmatter、命令、链接和 `git diff --check`；不强制本地重跑完整应用测试，但仍必须等待远端 CI。
- 测试失败可做范围内最小修复并重测；**不修改 Golden、不删除/跳过失败测试、不更改 CI 以制造绿灯**。如果不能修复，留下 Draft PR 和真实失败证据。
- 需要真实 LLM / 真实 Kubernetes / 额外凭据或成本的验收，若未获当次授权，标 `NOT RUN` 或 `BLOCKED`。不要自动执行真实集群写入来满足合并条件。

### 3. 独立决定「可合并」与「可关 Issue」

这两个判断不同，不能混为一谈。

**PR 可自动合并的前提**：变更属于已授权开发范围；没有 P0/P1 可复现阻断、秘密泄露或越权写操作；适当的本地验证通过；GitHub 本次 Head 的 CI 完整成功；GitHub 判定可合并；目标为默认分支。普通 Demo 代码无须额外独立 Reviewer。

**Issue 能自动关闭的前提**：读取 Issue 的全部明确验收项，逐项找到真实证据并确认完成；没有未解决的必需 Gate、历史 FAIL、BLOCKED 或 NOT RUN。只有此时才在 PR Body 独立一行写 `Closes #<issue>`。否则写 `Refs #<issue>`，即使代码可以合并也必须保持 Issue Open。若 Issue 状态不明或已经关闭，先核对，不乱加关闭关键词。

**额外检查**：检查本分支提交消息以及 PR Body 是否已经包含 `Closes` / `Fixes` / `Resolves` 等 GitHub 关闭关键词，防止在 `Refs` 路径下被其他文本意外关闭。存在不符合验收判断的自动关闭关键词时，先修正 PR Body；如果来自提交历史且无法安全纠正，停止自动合并，不做危险历史重写。

### 4. 创建或更新 Draft PR

1. 如果本分支已有 Open PR，复用并更新，不重复创建；否则创建 Draft PR。仅推送当前任务分支，绝不直接 push `main`；禁止 `--force` / `--force-with-lease`。
2. 使用实际 Diff 和测试结果编写**中文**标题与描述，必须包含：变更目标、范围、关联 Issue、测试证据（命令与结果）、验收等级、未完成项/风险、是否可以自动合并。不把「测试未执行」写成「通过」。
3. 先执行 `mkdir -p .local/submit-pr`，将临时 PR 正文保存到被忽略的 `.local/submit-pr/pr-body.md`（避免被提交）。按需执行：

   ```bash
   gh pr create --draft --base main --head "$(git branch --show-current)" \
     --title "<准确的 PR 标题>" --body-file .local/submit-pr/pr-body.md
   # 已存在 PR：
   gh pr edit <PR编号> --body-file .local/submit-pr/pr-body.md
   ```

4. 在 GitHub 回查 `gh pr view <PR编号> --json number,url,body,baseRefName,headRefOid,isDraft,mergeable,mergeStateStatus,closingIssuesReferences`；确保正确仓库、Head、目标分支和 `Closes/Refs` 语义。不把普通 Issue 文本引用误判为自动关闭关联。

### 5. 等待 CI、验证并**直接自动合并**

1. 检查 `gh pr checks <PR编号> --json name,bucket,state,link`。读取实时 `.github/workflows/ci.yml` 与 GitHub 检查列表，确认期望的 Job（通常 `python`/`web`/`compose`）均实际出现；空列表、缺失 Job、失败、取消、超时、等待外部批准均不得判 PASS。`skipping` 只有明确属于非必需项时才可接受；本项目三项基础 CI 缺失或跳过应停止。
2. CI 仍在运行时主动查询并等待，最长约 **15 分钟**；不要反复重新启动整套 CI。超过等待时间则维持 Draft，报告 `PENDING`，让下一次调用 `$submit-pr` 继续。
3. 检查无失败或待处理 Job 后，**仅当 PR 仍为 Draft** 执行 `gh pr ready <PR编号>`；如果已经是 Ready 则跳过。若转 Ready 触发新检查，必须再次等待全部通过；重新读取 Head SHA、base、mergeability、Review/Ruleset 状态及关联 Issue。
4. 未经授权不得绕过 Branch Protection、Ruleset、Merge Queue 或 Review Requirement；禁止 `--admin`。若 GitHub 规定必须 Review 或进入 Queue、无法立即合并，记录 `BLOCKED` 或平台队列状态；不要报告 MERGED。
5. 仅当所有合并条件仍成立，**无需再次征求用户确认**，执行（实际编号和 SHA 用实时值）：

   ```bash
   gh pr merge <PR编号> --squash --match-head-commit "<刚刚复核的 headRefOid>"
   ```

   推荐 Squash，保留简洁的 `main` 历史。不默认使用 `--delete-branch`，避免删除用户还在使用的 Worktree 分支；清理交给用户决定。
6. 若合并时 Head 已变化、策略阻断、CI 更新或 API 失败，停止并重新核验；**不盲目重试、不改用管理员绕过**。

### 6. 合并后回查（必须）

- 查询 `gh pr view <PR编号> --json state,mergedAt,mergeCommit,url`。只有 GitHub 显示已 Merge 才标 `MERGED`。
- 若 PR 使用 `Closes #N`，执行 `gh issue view N --json state,closedAt,url`，确认 Issue 已 Closed；若仍 Open，标记 `AUTO_CLOSE_FAIL`，**不要手动关闭来伪装自动关闭成功**，说明可能的关联/仓库设置问题。
- 若使用 `Refs #N`，检查 Issue 仍然 Open（如果其他并发操作改变状态，如实报告）。
- 不替换原始证据、不改历史验收记录、不自动部署/操作真实 Kubernetes、不清理其他 Compose/Worktree。

## 最终交付格式（控制在一屏内）

- **BASELINE**：仓库、工作分支、base、Head SHA。
- **PR**：编号、URL、`MERGED` / `DRAFT_BLOCKED` / `PENDING` / `MERGE_QUEUE`；实际 merge SHA（有才写）。
- **CHECKS**：本地实际命令与结果；GitHub 各项 CI 的真实状态。注明 Fake/Mock/Real 验证等级。
- **ISSUE**：编号、`Closes`/`Refs` 决策与理由；合并后的实时 Issue 状态。
- **RISKS**：未验证、已知 FAIL/BLOCKED/NOT RUN 与停止原因。

## 禁止事项与例外

- 不创建额外的合并机器人、独立 Review Agent、复杂 GitHub Actions；优先使用原有 CI 与 `gh`。
- 不把「所有必需测试通过」简化为「PR 能点 Merge」。不为了自动化降低现有 CI、权限或证据门槛。
- GitHub Actions 工作流/权限边界本身的变更，如会使现有校验失效、扩大权限、绕过审批，**不允许本 Skill 自行认定为安全并自动合并**；应当交由用户确认。
- 不越权执行 K8s `apply/delete/scale/patch/update`，不创建有写权限的 Token，不擅自修改 RBAC，不运行破坏性 `docker` 清理；这些需要单独明确授权。
- Skill 仅指导 Codex 调用已有 Git/GitHub/测试工具，不是强制安全策略，也不是项目运行时 LangGraph Skill。
