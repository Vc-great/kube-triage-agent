# Issue #72：Evidence Reviewer Demo-first V2 验收与运行

Refs #72。权威 Gate：[V2 设计](plans/issue-72-evidence-reviewer-subagent.md)。本报告只证明合成协议与工程集成，不证明真实模型质量或真实集群根因。

## 基线与实现

2026-10-23 `git fetch origin`：`origin/main=75de7ced6f39dc4a290835c9922613fe29fc36f5`，Planning #87 已合并；#74 的 S1 已合并，#69 仍 Open，main 无 Offloading Graph。使用 AO 提供的独立 linked Worktree `reviewer-demo`，从最新 origin/main 创建 `ao/reviewer-demo/issue-72-v2`。未改写 [S1 历史 FAIL/STOP](issue72-evidence-reviewer-s1.md)。

环境：macOS / Python 3.13.14 / Aegra 0.10.8 / deepagents 0.7.28 / LangGraph 1.2.14 / pnpm 10.5.1 / Next 16.3.8。复用 Host uv/pnpm 缓存与已有 `pgvector/pgvector:0.8.7-pg18-bookworm`，未改锁文件。

复用 S1 `build_graph`、`ReviewBoundary`、原生 `SubAgentMiddleware/task`、零执行工具 Reviewer、Manifest/签记与 schema/引用校验。新增独立 Entry/Profile、主/子 FakeModel 和薄启动入口；启动器复用 Skills 的进程、端口、dotenv、环境清洗和容器归属检查。正式 agent/B1/Skills 未注册 Reviewer。Web 仅增加标签/新 Thread 按钮，直接复用 Tool Call/Result、Thread、SSE 和 PG Checkpoint。

## V2-A 真实失败与最小修复

1. **历史探针 FAIL 保留**：原 `_ReviewGraph` 可启动，`POST /assistants/search`、`POST /threads` 均 200；首轮 `POST /threads/{id}/runs/stream` HTTP 200，但 SSE `error=ReviewFailure`，State `next=[model]`、`缺少受信执行轮次；拒绝模型调用`。首个失败 Run：`506085fe-2757-43d0-8752-70b7496c9ae0`。HTTP 200 不当作执行成功。
2. Aegra `langgraph_service.py` 会 `graph.copy(update={checkpointer,store,config})`；S1 的属性委托返回了内部裸 Graph。新增显式 `copy()`，返回同类包装器，从而保留受控作用域。未关闭任何签记/引用校验。
3. **第二次探针 FAIL 保留**：Reader 已成功，但默认 25 步在 task 前 `GraphRecursionError`（Run `fd15206f-638c-4486-9ffa-e45d3e3fbe36`）。包装器现在先合并内部 Graph config，再调用 `ensure_config`；独立 Entry 的有限递归上限为 100。12 次父决策、2 次子决策、Reader/Todo 预算与 20 秒 task 上限不变；调用方仍可设置更低 recursion_limit。
4. 适配后真实 SSE `end.status=success`，四 Reader + Todo + 原生 task 配对，最终 `COMPLETED/SUPPORTS`，PG `state.next=[]`。正例 Run `75d949f3-a325-4c21-b7a3-53550c758b82`。后续冻结测试再次验证完整闭环。

`review-web` 是显式 test-only Mock 数据集，复用 memory-web 四 Pod fixture；Pod 返回最小结构，Events 只提供 CrashLoop 的一个样本，以免演示资料超过现有 800-byte 摘录预算。**没有放宽截断规则**；ImagePull/OOM 的 SUPPORTS 仅引用本轮有效 Pod 详情，不用该 CrashLoop Event 证明其他 Pod。403、8.2 秒延迟、错误 ConfigMap 均为测试注入，不代表真实集群行为。

## 一条命令运行

在没有 server/Web dotenv 的独立工作树准备当前锁定环境（复用本机工具/缓存）：

```sh
(cd server && uv sync --frozen --python 3.13)
(cd apps/web && pnpm install --frozen-lockfile)
make dev-deep-review-demo
```

打开 `http://127.0.0.1:13072`，Graph 为 `deep_diagnosis_review`，本地合成 API Key 为 `skills-demo-local-only`（复用启动器的公开测试值，不是真实凭证）。默认 API/PG 为 12072/15472，Mock MCP 为 8000；任一端口占用会停止启动，不清理其他项目。可用 `python3 scripts/review_demo.py --api-port ... --web-port ... --db-port ...` 指定独立端口。

依次提交：`诊断 crashloop-pod CrashLoopBackOff`、`你好`、`诊断 imagepull-pod ImagePullBackOff`。应看到四 Reader、write_todos、`task(evidence-reviewer)` 及 Tool Result；最终报告区分观察/推断/未知和 `review_status/verdict/evidence_refs`。问候只返回 SKIPPED/UNKNOWN，不添加 Reader/task。普通完成轮次可刷新、侧栏重进；新 Reviewer Thread 不继承旧第二意见。主报告的 Pod 字段只取本轮有效 Reader，子模型自由文本不直接成为事实。

其他输入：`诊断 forbidden-pod 403`、`诊断 timeout-pod timeout`、`缺证据`、`诊断 crashloop-pod 矛盾`、`诊断 crashloop-pod Reviewer失败`、`诊断 malformed-pod 错误证据`、`诊断 crashloop-pod 错误引用`。在非问候输入尾部加 `Reviewer OFF` 可跳过 FakeModel 的 task；这只是合成协议对照开关，不是生产权限开关。

Ctrl-C 仅停止本次子进程及带 `ao.session` 标签的唯一临时 PG 容器；数据库为临时数据，停启后新建实验 Thread。回退为停止此 Profile 后启动原有 Graph，无生产配置或迁移需要回滚。

`--persistence` 按需迁移本次隔离 PG 并开启已有 History/Evidence API 和 Web Hook；默认关闭。本期基础验收使用 Aegra 原生历史，不依赖业务表。可选持久化模式尚未单独验收，保持 NOT RUN。

## 实际命令与结果

```sh
# server/
uv run --frozen --offline ruff check src tests ../scripts/skills_demo.py ../scripts/review_demo.py
uv run --frozen --offline pytest -q
uv run --frozen --offline pytest -q tests/test_deep_diagnosis_review.py tests/test_deep_diagnosis_review_execution.py tests/test_deep_diagnosis_review_spike.py
ISSUE72_TEST_API_URL=http://127.0.0.1:12072 uv run --frozen --offline pytest -q -s tests/test_review_protocol.py
# apps/web/
pnpm lint
pnpm build
# repo/
git diff --check
```

- Ruff PASS；全量首轮 **884 PASS / 40 SKIPPED，178.78 秒**，此轮早于新增 copy 回归及最终 text-block 修复，不声称覆盖最终全部变更。
- 最终 Reviewer 专项 **105 PASS，76.26 秒**（含 copy/config、执行作用域和 S1 负测）。
- 最终真实 HTTP/SSE/PG **23 PASS，31.04 秒**：11 冻结案例 OFF/ON + 三轮/刷新/隔离，使用 Web 同款 text-block 输入和 `stream_subgraphs=true`；未用 MemorySaver 代替 PG。
- Web lint PASS（18 条既有 warning，0 error），build PASS；构建有既有 Tailwind 模块格式 warning。
- 初轮 Ruff 的脚本执行位/import 顺序及新增测试类字段问题均已修复；不把初次失败删成 PASS。

## 冻结协议对照

数据集：`server/tests/fixtures/issue72-review-cases.json`。每个有工具案例实际运行四 Reader，逐一验证 Tool Call ID/Result 配对；OFF task=0，ON 除问候/缺证据 task=1。时长为本机本轮端到端秒数，包含 HTTP、PG 和 Mock；没有真实 Token 或付费调用。

| Case | OFF 秒 / 状态 | ON 秒 / 状态 / verdict |
| --- | --- | --- |
| CrashLoop | 0.639 / UNREVIEWED | 1.075 / COMPLETED / SUPPORTS |
| ImagePull | 0.585 / UNREVIEWED | 0.619 / COMPLETED / SUPPORTS |
| OOM | 0.541 / UNREVIEWED | 0.639 / COMPLETED / SUPPORTS |
| 缺证据 | 0.175 / UNREVIEWED | 0.230 / UNREVIEWED / UNKNOWN |
| 403 | 0.578 / UNREVIEWED | 0.597 / COMPLETED / INSUFFICIENT |
| Reader timeout | 9.377 / UNREVIEWED | 8.743 / COMPLETED / INSUFFICIENT |
| 问候 | 0.238 / SKIPPED | 0.130 / SKIPPED / UNKNOWN |
| 矛盾候选 | 0.545 / UNREVIEWED | 0.771 / COMPLETED / CONTRADICTS |
| Reviewer failure | 0.575 / UNREVIEWED | 0.682 / FAILED / UNKNOWN |
| 错误 Pod 类型 | 0.453 / UNREVIEWED | 0.575 / COMPLETED / INSUFFICIENT |
| 错误引用 | 0.492 / UNREVIEWED | 0.536 / FAILED / UNKNOWN |

OFF 所有 verdict=UNKNOWN。`task.status=success` 仅表示工具协议执行成功；COMPLETED/INSUFFICIENT 仍不支持肯定根因，FAILED 的 task.status=error。SUPPORTS/CONTRADICTS 都只是有界证据与候选的一致性咨询。

## 逐 Gate

| Gate | 当前结果 | 实际证据与限制 |
| --- | --- | --- |
| V2-R0 | PASS | 最新基线、#74/#87 合并与 #69 去重；复用 Reviewer/Reader/History，独立工作树/分支 |
| V2-R1 | PASS | 原入口失败及最小 copy/config 修复如上；真实 assistants/threads/runs/stream/state/PG，成功结束且 next=[] |
| V2-R2 | PASS | 真 MCP 四 Reader、原生 task、S1 SDK 专项与双 FakeModel；Reviewer 非空工具绑定拒绝，Host 保留零执行工具边界 |
| V2-R3 | PASS | 11 固定案例含错误证据/引用/403/超时/问候/子代理失败；中文报告与状态；旧签记负测仍通过 |
| V2-R4 | PASS | AO 自动浏览器可见 Reader/Todo/task/完整报告；完成轮次多轮、问候、刷新和新 Thread；侧栏选择历史 Thread 后可读完整报告；新 Thread 无旧消息。真人测试 NOT RUN（#86） |
| V2-R5 | PASS | 首轮全量和最终 Reviewer 专项通过；正式 Graph/Memory/HITL/Repair 未改；独立 Profile 可停止，既有启动器默认路径不变。旧 task 中途 Resume NOT RUN/不支持 |
| V2-R6 | PASS | 11 案例 OFF/ON，23 真协议测试；次数/配对/状态/耗时见表；真实模型质量/Token 为 NOT RUN/UNKNOWN |
| V2-R7 | BLOCKED | 本地检查已通过；Implementation PR、最终 CI 和独立 AO Review 待补链接与结论，不提前判 PASS |

## 未执行与边界

真人浏览器、真实 Provider 效果评估留 [#86](https://github.com/Vc-great/kube-triage-agent/issues/86)：NOT RUN。真实 Kubernetes 读写、付费模型、敏感日志/Trace 出站：NOT RUN。旧中断 task Resume、跨进程 nonce、生产 State 认证：不支持/NOT RUN。可选业务持久化模式：NOT RUN。

AO 浏览器曾过早读取到空白最终气泡；等待 run 完成后与重开 Thread 均显示完整报告，未修改 Web 流合并逻辑。侧栏选择另一条诊断 Thread 时等待 SKIPPED 超时，核对后其实际 COMPLETED 报告正常；测试期间重建临时 PG 后访问旧 Thread 的 404 记录保留，不能称跨重启恢复 PASS。

没有新增证据表、History API、第二服务器或复杂 UI。Reader Namespace/8s/16KiB/参数校验与 Repair/HITL 审批边界不变。未合并 Implementation PR，未关闭 #72；S1 历史失败和其他 Issue 的未修复缺陷不因本次 PASS 消失。
