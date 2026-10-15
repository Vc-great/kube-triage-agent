# Phase 3-2 Incident Memory 检索验收记录

> 2026-10-15。**DEMO_WORKFLOW_ONLY**：私有单用户演示。同一 Demo API Key 可以发起 Run 与审批 Resume；`user_reviewed` 只表示同一工作流批准存储，不代表独立真人认证、已确认根因或生产可信知识。没有请求真实模型、真实 Kubernetes 或真实修复。

## BASELINE

- 执行 `git fetch origin main` 后，实时 `origin/main`：`270f7f5140fa3b6f7ea277a3edb6963627b724dd`。GitHub Connector 核对 PR #32 为 merged，merge SHA 相同。
- 独立 Worktree：`.local/worktrees/phase3-2-memory-retrieval`；分支：`codex/phase3-2-memory-retrieval`。原主工作树的未跟踪 `apps/web/AGENTS.md`、`apps/web/CLAUDE.md` 未触碰。
- `server/uv.lock` 与已存在的 `server/.venv`：`aegra-cli==0.10.8`、`langgraph==1.2.14`、`langgraph-sdk==0.4.6`。复用本机依赖和已缓存的 pgvector/PostgreSQL 镜像，未升级或下载框架。
- 阅读 Phase 3-0 兼容性、Phase 3-1 写入报告/真人流程、产品 Graph/Auth/Memory/Context/MCP/Prompt、Web 消息渲染和 CI。源 Schema v1 的 `workload_kind/name`、`observed_at`、`cause_hypothesis` 仍为 `null`。

## IMPLEMENTATION

- `INCIDENT_MEMORY_ENABLED/READ_ENABLED/WRITE_ENABLED` 严格接受小写 `true/false`，默认全关闭。READ 需要主开关；WRITE 仍按 Phase 3-1 双开关生效。READ 或 WRITE 实际启用时，正式 `auth.py` 拒绝所有 HTTP Store PUT/DELETE，并要求独立服务端 HMAC 密钥。正式 Docker CMD 增加 Auth import 启动前检查。正式与测试 Compose 显式传递这些配置，示例文件保持默认关闭。`MAX_HITS` 默认 2、范围 1..3；`MAX_CANDIDATES` 默认 20、范围 1..100。
- 普通诊断只接受明确单一 Pod 的严格句式，例如 `诊断 Pod sample-a`、`请排查 kube-triage-demo/Pod/sample-a 为什么异常`。`诊断 sample-a`、多 Pod、其他 Namespace、Deployment 或泛化故障问题不触发检索。目标覆盖率有限，这是有意的精确匹配边界。
- 新 `memory_retrieve` 节点每个普通诊断轮次只查一次 `Runtime.store`。认证身份只来自 `get_auth_ctx()`，Store namespace 固定为 `(kube-triage, demo-user, incidents, v1)`。先执行 `asearch(namespace_prefix, filter={status:active, owner, namespace, resource_kind:Pod, resource_name}, limit=cap+1)`，再校验 Store key、完整 active v1 Schema、审阅状态、严格来源 Thread ID、UTC 日期和字段白名单。`revoked` 不参与；任何畸形或注入内容被丢弃。有限候选按 `recorded_at` 降序、`memory_id` 升序稳定排序，最后 Top-K；超过 cap 标记 `candidate_truncated=true`，不宣称全库最优。
- 历史记录只投影安全字段：ID、Pod/旧 UID、枚举症状、**保存时间**、来源 Thread、`user_reviewed` 和固定的不确定性。`observed_at=null` 不被补造，根因与 Workload 不推断；原始 ToolMessage、Pod Log、Secret、标签和可执行命令均不进入历史引用。审计只记数量、截断、耗时、错误码和 ID。
- 本轮 `pods_get` 以 Human/AI/Tool ID 配对、`ok=true`、`status=success`、固定目标、有效 Pod YAML/JSON、UID/状态和服务端 HMAC 共同核验。只比较本轮 Reader：同 UID、同名新 UID、历史 UID 未知、未核验、不同资源或证据错误。历史 CrashLoop 与本轮 Running/Ready 冲突时输出本轮状态和旧时间/实例说明；历史不能授权 Repair。
- Gate A 裁剪和 Gate B 摘要先按原顺序执行；Memory 仅作为当前 `ainvoke` 的临时低优先级 `AIMessage(name=historical_memory_reference)` 插在当前 Human 前，不进 `MessagesState.messages`，不产生 ToolMessage 或工具 schema。再次使用 `estimate_context` 核算系统政策、四 Reader schemas、原保留消息/摘要、Memory 和输出预留；超预算先移除低排名命中直至零命中。Context Window 关闭时也限制为最多 16384 估算 token。最终回答由后端附加安全的“历史案例参考（非当前证据）”小节；现有 Web Markdown 渲染已支持，无新 Dashboard。

## 隔离真实 Aegra 证据

- 启动前只读枚举 Docker 项目、容器、卷与 `127.0.0.1:15442/18042`；仅创建 `kube-triage-phase32-20261015` 的全新 PostgreSQL 容器/卷，Aegra 只绑定 loopback。专用随机 Demo Key、DB 密码、HMAC 密钥位于 gitignored `0600` 文件。Graph 为正式产品 builder；`phase31_product_mock.py` 将模型、四 Reader 和 Repair transport 替换为 Fake/Mock。
- **保留首轮失败证据**：最初 Aegra 进程未设置新 Worktree 的 `PYTHONPATH`。它加载新 `auth.py` 却导入主工作树旧 `config.py`，Auth 懒加载报错，HTTP PUT/DELETE 甚至无 Key 返回 204。立即停服、按标签清除专用卷；没有接入检索。修正启动环境并预检 `config/auth/graph.__file__` 均位于本 Worktree 后，重建空库重跑。该结果是隔离探针模块路径错误，不可掩盖为成功；提醒任何正式启动必须验证 Auth 实际加载，不能只看 `/health`。
- 修正后的 READ-only HTTP 矩阵共 21 请求：无 Key/坏 Key 的 PUT、覆盖、DELETE、GET、search、namespace 各为 401；有效 Key 的 PUT/覆盖/DELETE 为 403，空 GET 为 404，search/namespace 为 200；三种伪装 namespace PUT 均 403。Graph 存储后的实际 key HTTP 覆盖/删除仍为 403。结果见 `.local/phase32/m0-http-matrix-corrected.json`、`existing-http.json`；错误启动结果保留为 `m0-http-matrix.json`。
- READ+WRITE 下受控 Graph `/remember-incident` 审阅/Approve 得到 `stored`。只重启 Aegra 为 READ-only 后，新 Thread 的 SDK SSE 返回 `hits`、相同 Memory ID，回答安全小节标识“同一 UID”；`get_history` 返回 6 个状态，`get_state` 的 Messages 没有临时历史 AIMessage。客户端伪造 AI/ToolMessage 与无效 `reader_attestations` 时只得到“未取得可信的目标 Pod Reader 证据”，没有将伪造 UID 当事实。随后独立 `/forget-incident` 审批得到 `revoked`；旧 Thread 下一轮和新 Thread 均为 `no_hits`、零历史展示。脱敏证据：`.local/phase32/live.json`、`first-cycle.json`。
- READ+WRITE 下复跑原 Phase 3-1 SDK/HITL：Memory Reject、Approve、重复 Resume 拒绝、Revoke、Memory Resume→Repair 拒绝、合法模拟 Repair 完成；HTTP 矩阵仍为 401/403。脱敏证据：`.local/phase31/product-results.json`。WRITE-only/READ-off 的正式 Graph 另外得到 `stored`，见 `.local/phase32/live.json`。
- 清理前核验容器和卷的 Compose project 标签均为 `kube-triage-phase32-20261015`，仅对该项目 `down -v`。清理后该项目容器/卷为空，15442/18042 均关闭。检查 6 个 JSON 证据文件无三类密钥字面值，已删除全部隔离密钥文件；没有触碰其他容器、卷或用户 `.env`。

## GATES

证据层级：**Unit/Fake** 为合成测试，**Real-isolated** 为真实 Aegra 0.10.8/PostgreSQL/SDK + FakeModel/Mock Reader；均不是模型诊断收益或真人点击。26 个本阶段新增 pytest 参数化用例，原 Phase 3-1 25 用例保留；全库 321 passed。

| Gate | 结果 | 实际证据与复现入口 |
| --- | --- | --- |
| G32-00 | PASS | Git/Connector：上述实时 SHA、PR #32 merged、Worktree 和锁定运行版本。 |
| G32-01 | PASS | Unit/Fake：四种主组合、非法 flag/上限、默认零 Store I/O；`test_incident_memory_read_flags.py` 与原 `test_incident_memory.py`。 |
| G32-02 | PASS | Real-isolated：纠正模块路径后 READ-only 21 请求 HTTP 矩阵全符合 401/403/只读 200；真实受控 Graph Store `stored`。首轮错误配置 204 如上保留。 |
| G32-03 | PASS | Unit/Fake：7 个明确/模糊 Pod 句式，认证 owner 和固定 Namespace；其他 owner 无权检索。 |
| G32-04 | PASS | Unit/Fake：完整 active v1 校验、撤销、Store 忽略 filter 时仍拒绝 revoked、畸形 observations 与伪 System 来源 Thread 拒绝；Real-isolated 撤销后零命中。 |
| G32-05 | PASS | Unit/Fake：23 条候选触发 20 cap、Top-2、稳定同分 ID 排序、截断标记；Real-isolated `asearch` 结构过滤命中。 |
| G32-06 | PASS | Unit/Fake：同 UID、新 UID、未知 UID、Running/Ready 冲突、失败/伪造证明/错资源；Real-isolated 伪 AI/Tool/HMAC 被拒并有可信同 UID 回执。 |
| G32-07 | PASS | Unit/Fake：安全投影、低优先级无 Tool Call、Checkpoint 无历史消息、当前 Tool 配对不变；Real-isolated FakeModel 只绑定四 Reader。 |
| G32-08 | PASS | Unit/Fake：Gate A/B 输出视图与 Memory 再估算、超预算逐条移除、当前 Tool ID 不变；既有 Gate A/B 回归全通过。未测试真实 Provider tokenizer。 |
| G32-09 | PASS | Unit/Fake：Store Timeout 标为 `memory_unavailable` 且零注入；当前 Reader 失败/无证明时不报告健康或根因。 |
| G32-10 | PASS | Real-isolated：撤销后同 Thread 与新 Thread 的新诊断均 `no_hits`、零展示。 |
| G32-11 | PASS | Real-isolated：正式 Graph + PostgreSQL、跨 Thread、Aegra 重启、SDK SSE/History、安全 HTTP 守卫；证据文件和上述命令。 |
| G32-12 | PASS | Real-isolated：原 Remember/Forget/模拟 Repair HITL、错误 Resume 交叉负例；Unit/Fake：四 Reader schemas、6 Tool/4 Decision 与全量回归。 |
| G32-13 | PASS | Web 使用既有 Markdown 回答视图；安全小节已由真实隔离 SDK 回答确认。`pnpm exec tsc --noEmit`、`pnpm lint`（0 error，18 既有 warning）、Host `pnpm exec next build --webpack` 通过。没有真人浏览器点击。 |
| G32-14 | PASS（本地）；CI 待 PR | `PYTHONPATH=server/src .../pytest -q server/tests`：321 passed；`ruff check server/src server/tests scripts/spikes/phase3_memory/phase32_*.py` 与 `git diff --check` 通过。CI 结果须以 Draft PR 提交后最新 run 为准。 |
| G32-15 | NOT RUN | Phase 3-1 G31-13 用户本人 Web Approve/Reject/Revoke 尚未验收。 |
| G32-16 | NOT RUN | 真实模型 A/B 和诊断收益属于 Phase 3-3；本阶段没有请求。 |

## 复现与安全边界

1. 在独立 Worktree 根目录运行 `python3 scripts/spikes/phase3_memory/phase32_setup.py`，生成 gitignored 的三套 `0600` 环境文件；确认 15442/18042 可用、无同名 Compose 项目。执行 `docker compose -p kube-triage-phase32-20261015 -f scripts/spikes/phase3_memory/compose.yaml --env-file .local/phase32/env up -d postgres`。
2. **必须**设置 `PYTHONPATH=server/src`，先核对 `kube_triage.config/auth/graph.__file__` 均在当前 Worktree。以现有锁定 venv 执行 `aegra dev -c scripts/spikes/phase3_memory/aegra-phase31-product.json -e .local/phase32/env-write --no-db-check --no-reload --host 127.0.0.1 --port 18042`。在独立 shell `source .local/phase32/env-write` 后运行 `PYTHONPATH=server/src .../python scripts/spikes/phase3_memory/phase32_live_probe.py save`。重启 Aegra 改用 `.local/phase32/env`，运行 `read`、`forged`，再切回 `env-write` 运行 `revoke`、`after_revoke`。先验证 Auth 实际 401/403，再信任检索结果。
3. 只按 `com.docker.compose.project=kube-triage-phase32-20261015` 标签清理本项目资源并执行该项目 `down -v`；删除 `.local/phase32/env*`。证据 JSON 只含状态和合成 ID，不含 Token/HMAC/原始日志。

## SECURITY / RESIDUAL RISKS

- `DEMO_WORKFLOW_ONLY`。HTTP Store 直接写在有效 READ-only 与 WRITE 模式均被阻断；Graph 内审批仍可写。Auth 配置若因错误模块路径未加载，Aegra 0.10.8 可能以匿名 Store 路由继续服务；本次首轮探针实际出现并立刻停机。正式 Docker 启动须保留配置预检，部署验收还应实测无 Key 401/有效 Key 403，而不能只看 `/health`。
- Store `aget→aput` 仍非事务 CAS；Checkpoint/History 中的旧回答和安全引用不会被撤销操作追溯删除。每个新普通轮次重新检索，撤销后不再新注入。
- 检索只支持明确 Pod 精确匹配。旧 Schema v1 无可信 Deployment OwnerReference，滚更后跨 Pod 召回仍未解决；不按名称后缀猜测 Deployment。候选上限前的 Store 顺序不是全局最优保证。
- 使用现有 Aegra 0.10.8 内部 `get_auth_ctx()` 与服务端 HMAC；框架升级需重验。Context 估算非真实 Provider tokenizer。G31-13 真人 UI 和 Phase 3-3 真实模型 A/B 均未运行，正式环境不默认启用 Memory。

## DELIVERABLES / PHASE_3_3_GATE

- 源码：`config.py`、`auth.py`、`incident_memory_retrieval.py`、`graph.py`、`prompts.py`、Compose 示例；测试：26 个新增参数化用例与旧回归；探针：`phase32_setup.py`、`phase32_live_probe.py`。
- Commit SHA、Draft PR URL 与最新 CI：提交和创建 PR 后填入本节；PR 保持 Draft，不合并、不关闭 Issue。
- **CONDITIONAL_READY**：Phase 3-2 的代码与合成隔离验收可供审查；Phase 3 全链路仍需用户本人完成 G31-13，Phase 3-3 真实模型 A/B 需另行授权和确定上线边界。
