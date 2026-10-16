# Issue #37 验证记录

截至 2026-10-16。本表的 PASS 仅指写明的 Fake Model / Mock MCP / 本地浏览器范围；Real Provider、Real Kubernetes 和真人 HITL E2E 均未运行。原始的本地脱敏观察摘要见 [evidence/issue37-local-smoke.md](evidence/issue37-local-smoke.md)。

## 基线与命令

- 实施时 `git fetch origin main` 后 `origin/main=7c3e40e4cdb4c6320f2b325f21c0a63e6dd24c94`；独立 Worktree `/private/tmp/kube-triage-issue37-agent-execution-timeline`，分支 `codex/issue37-agent-execution-timeline-impl`，起点 HEAD 与 `origin/main` 相同，起初 clean。主工作树已有未跟踪文件，未修改。Issue #37、#28 当时 OPEN；PR #36 MERGED。
- 实装/锁定版本：Aegra 0.10.8，Python LangGraph 1.2.14、langgraph-sdk 0.4.6，前端 `@langchain/langgraph-sdk` 1.12.0、Next 16.3.8。复用主仓既有 `.venv` 和 pnpm 依赖，没有下载新包。
- 端口和卷先检查，再使用单独 Compose Project `kube-triage-issue37-timeline`；只操作其 API、PG、Redis、Mock MCP。`docker compose -f /private/tmp/issue37-smoke/compose.yaml -p kube-triage-issue37-timeline config --quiet` 退出码 0。该临时 Compose 测试夹具不属于应用交付，也不依赖真实集群。
- 后端：`cd server && PYTHONPATH=src /Users/vc/code/kube-triage-agent/server/.venv/bin/python -m pytest -q`；`/Users/vc/code/kube-triage-agent/server/.venv/bin/ruff check src tests`。
- 前端：`cd apps/web && node --experimental-strip-types --test src/lib/agent-progress.test.mjs`、`pnpm lint`、`pnpm exec tsc --noEmit`、`pnpm build`。
- SSE 复现：在隔离 Aegra 建 Thread，向 `/threads/{thread_id}/runs/stream` 提交 `{"assistant_id":"agent","input":{"messages":[{"role":"human","content":"你好"}]},"stream_mode":["values","custom","messages-tuple"]}`，按 SSE `event:` 和 `data:` 逐条核对。Context 场景用 8 个合成闭合历史轮次和预算 6500；Reader 场景用 Mock MCP。实际输出的脱敏摘要已固化到 evidence 文件。独立 Web 用 `NEXT_PUBLIC_API_URL=http://127.0.0.1:12437 pnpm dev --hostname 127.0.0.1 --port 13437` 验证。

## T00–T17

统计：15 PASS、3 NOT RUN、0 FAIL、0 BLOCKED。NOT RUN 为 T09、T13、T16。

| ID | 状态 | 分层与证据 | 边界 |
| --- | --- | --- | --- |
| T00 | PASS | fetch、SHA/版本/端口/卷检查；隔离 Compose `config --quiet` 退出 0 | 未检查真实 K8s |
| T01 | PASS | Aegra `custom` 与 `values`、`messages` 同 Run；React `onCustomEvent` 收到固定事件并显示 Timeline | Fake Model |
| T02 | PASS | 浏览器“你好”得到普通 AI 正文、仅模型/答复进度，无虚构工具与摘要 | Fake Model |
| T03 | PASS | 无裁剪场景不发 summary completed；原 Gate A 单测和普通浏览器 Run | Fake Model |
| T04 | PASS | Gate B 关闭，SSE 仅 trim completed、模型和答复；`summary_status=None`，21 个消息事件无内部 JSON | Fake Model + SSE |
| T05 | PASS | 摘要 started→completed；`summary_status=ready`；21 个 `messages` 事件没有内部 JSON，`values` 有正文；浏览器显示“历史参考已采纳” | Fake Model + SSE + UI |
| T06 | PASS | 同 Thread 第二 Run 仅 `cache_hit`，无新摘要 started；浏览器显示缓存命中文案；原 Gate B 单测 | Fake Model + SSE + UI |
| T07 | PASS | `invalid_schema` 为 fallback，`summary_status=failed`，21 个消息事件无 JSON，仍有最终正文；浏览器显示“摘要失败，已回退” | Fake Model + SSE + UI；超时仅原单测 |
| T08 | PASS | Mock MCP 单工具 `call_issue37_0` started→completed，与成功 ToolMessage 配对；浏览器 Tool 卡和 Timeline 均显示 | Mock MCP + UI |
| T09 | NOT RUN | Mock MCP SSE 已核对两个 Tool Call 的顺序与成功/失败结果；浏览器尚未证实同一 Run 中两个 Tool 行，所以整项不记 PASS | 工具预算由原单测覆盖 |
| T10 | PASS | Mock MCP 的 missing/error 返回 failed；单测 timeout 类型和预算耗尽分别为 failed/skipped，无 success；原 ToolMessage 错误分类保留 | Mock MCP + unit |
| T11 | PASS | 单测把伪指令/伪 token 放入 Tool Result，ToolMessage 保留数据而 Progress 事件不含该文本；前端 Schema 测试拒绝动态 label、额外字段、非 Reader 名称 | unit + UI 守卫；未调用真实 Provider |
| T12 | PASS | 浏览器新 Run/新 Thread 清空旧 Timeline；前端单测同 `event_id` 去重、跨 Thread 拒绝、64 条上限 | 同 Thread 并发晚到事件见下方限制 |
| T13 | NOT RUN | 未构造可控慢 Run 来验证 Cancel/断线；实现不从断线推断 terminal | 不宣称已验收 |
| T14 | PASS | `REPAIR_SIMULATED=true` 的 Fake Repair 在浏览器出现原审批卡，拒绝 Resume 返回无写入正文；测试夹具禁止写函数；原 `test_phase3b.py` 随全量 pytest 通过 | 未批准、未真实写 K8s |
| T15 | PASS | 浏览器刷新后正式 AI/Tool History 恢复，未持久化 Timeline 消失 | 本地 Aegra + UI |
| T16 | NOT RUN | Hide Tool Calls 的原始 Tool 卡隐藏且 Timeline 保留已验；`UIMessage`/`RemoveUIMessage` 分支保持，但没有产生原 UIEvent 的端到端夹具 | 不把静态检查算作 UIEvent 验收 |
| T17 | PASS | 本地 pytest 337/337、Ruff 退出 0、Node 测试 2/2、lint 退出 0（18 个既有 warning）、`tsc --noEmit` 退出 0、build 退出 0；Draft PR #38 首次 CI 的 compose/python/web 均 pass | [CI run 38910975348](https://github.com/Vc-great/kube-triage-agent/actions/runs/38910975348) |

## 流量、性能与安全结论

改动没有新增 `model.ainvoke` 或 `call_tool` 调用点，Graph 节点/边与预算常量未变。合成摘要首次 Run 的审计 `summary_calls=1`，第二 Run 的 `cache_hit` 为 `summary_calls=0`；Tool SSE 的 ToolMessage 数与实际 Mock MCP 调用一致（单工具 1、双工具 2）。这可证明本地夹具没有因 Timeline 触发额外调用；没有真实 Provider 的前后 Token 数值对照，不能声称 Token 消耗已量化不变。内部 JSON 在成功、invalid_schema 与 Gate B 关闭三组 `messages` SSE 中均未出现；正常最终正文独立存在于 `values`。

服务端输出字段与标签白名单、ID 长度、前端再校验可阻止 Tool Result/Prompt 原文进入 Timeline。Reader、Memory、Repair、HITL、Checkpoint 的权限与状态机没有修改。当前进度没有可靠的跨同 Thread 并发 Run 关联，也不持久化；重连时相同事件 UUID 去重，但晚到的不同 UUID 可能进入当前 Run 的内存态。Progress 仅供观察，不能代替 ToolMessage 或审批结果作权威判断。真实 K8s、真实 Provider、取消/断线、多工具浏览器单 Run 和 UIEvent 端到端仍待独立 Reviewer 按需验证。

## 历史失败与质量门禁

初始 Turbopack 跨 Worktree symlink、预算 2800 导致的 Gate A 安全失败、临时 Aegra 假图路径错误和旧 API 镜像缺依赖均保留在 evidence 文件中。修正各自的隔离测试配置后，最终本地门禁如上；没有改写历史失败或触碰用户现有 Compose 卷。Web build 保留项目原有 Tailwind module format warning，lint 保留 18 个既有 warning，均未被宣称为零警告。
