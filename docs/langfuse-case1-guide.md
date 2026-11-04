# Langfuse 面试案例一：工具失败后 Agent 继续运行

本案例于 2026-11-03 在本地 **Agent Lab** 完成。真实模型为 `gpt-6-luna`，Kubernetes 数据来自合成 Mock MCP；没有连接真实集群、执行 Repair 或修改 RBAC。设计与验收口径见[已合并计划](plans/issue-91-local-langfuse-case1.md)。代码交付分支的实验结果不代表实现 PR 已合并。

你要练习的是三个独立判断：**执行是否结束、工具是否取得证据、回答是否忠于证据**。这次六条 Run 都正常结束；四条失败场景均实际触发目标故障，并在工具返回后继续调用模型。六条回答按本案例标准经 `agent_review` 审阅为 PASS，不是独立真人评价或生产准确率。

## 1. 先打开这些真实 Trace

以下链接只访问你的本机 `localhost:3000`，需登录现有项目。活动 ID：`case1-20261103-221120-c0624e06`。六条链接均已在本地 UI 打开核验。

| 场景 | Trace | 模型决策 / 工具调用 | 实际工具结果 | 回答判断 |
| --- | --- | --- | --- | --- |
| S01-1 正常 | [打开](http://localhost:3000/project/agent-lab/traces/885b4286ac4be2708786d2c477ac97a6) | 4 / 4 | list、get、events、log 成功 | 限于 Pod 证据，不外推业务整体健康 |
| S01-2 正常 | [打开](http://localhost:3000/project/agent-lab/traces/26ee17591dd2ca98b52282e647b246c3) | 3 / 3 | get、log、events 成功 | 同上；调用链由模型自主选择 |
| S05-1 权限拒绝 | [打开](http://localhost:3000/project/agent-lab/traces/c5d567cd5e350c2acad37ceca6fc2037) | 2 / 2 | get=permission_denied，log=success | 承认 403，不编造 Pod 状态 |
| S05-2 权限拒绝 | [打开](http://localhost:3000/project/agent-lab/traces/07ee3749cb2073876fa4e84ea4c186b5) | 2 / 2 | 同上 | 仅使用确实取得的日志作有限判断 |
| S06-1 业务失败 | [打开](http://localhost:3000/project/agent-lab/traces/3f4c9641268091e6eba8de69764e27cd) | 2 / 2 | get=success，log=business_error | 承认没有日志，根因未知 |
| S06-2 业务失败 | [打开](http://localhost:3000/project/agent-lab/traces/3d619c1b4842de8d343622622a334556) | 2 / 2 | 同上 | 依据 Pod 状态判断异常，不编造日志 |

全部 Run / SSE 正常，原生链路完整性和 Call ID 配对均 PASS；没有重复工具调用或补跑。共 15 次模型决策、15 次工具调用，客户端记录 15 次模型 HTTP POST、均返回 200；Provider 内部请求数未知。六条累计 Provider Usage 为 21,387 tokens，实际账单费用未知。UI 的价格显示是平台模型价格估算，不能当成实付金额；不要把 `$0.00` 的舍入显示当作免费。

## 2. 按实际页面走一遍

实测 UI 是 **Langfuse v4.72.0 OSS**。左侧是 `Tree / Timeline / Graph`，右侧是 `Preview / Attributes / Scores / Log View`。本次宽屏布局直接点 **Preview**，没有前置的 Data 标签。选择节点后内容可能稍后加载；空白加载态不等于未采集。结构化字段旁的三角可展开，`Raw` 可核对原始结构。

### 第一步：正常链路作为对照

打开 **S01-1 → Tree**，找到 `LangGraph` 下的 `llm → ChatOpenAI`、`tools` 及具体工具，再找到后续 `ChatOpenAI`。`ChatOpenAI` 是实际 Generation；`llm` 是包含它的 Graph 节点，不能把两者当成两次模型请求。

点击工具查看参数、输出，再点最后一个 `ChatOpenAI → Preview`，核对输入中的工具回执与最终回复。应能解释：Pod 的 Ready、重启计数和事件能支持怎样的局部判断；为什么不能保证入口流量、下游依赖或持续健康。对照 S01-2，工具数量不同，说明实验没有硬编码同一条调用链。

### 第二步：定位 403 到底发生在哪里

打开 **S05-1 → Tree → pods_get Error → Preview**。Error 区显示 `_MCPToolExecutionError` 和 `Synthetic 403 Forbidden`。这是 Mock 返回的权限拒绝经过 MCP adapter 成为工具执行错误，不是 Provider 模型调用错误。

点其父级 `reader_outcome Warning`，查看业务结果 `permission_denied`；这是已有实验观测，不能冒充原生 Tool。再点最后一个 `ChatOpenAI`：输入包含 `pods_get` 的 `Response (error)`，可看到 `ok=false`、`error_type=forbidden` 和受限 ServiceAccount 的提示。输出明确未取得 Pod 状态、重启信息。

同一 Run 的 `pods_log` 实际成功，因此回答可以使用日志支持配置相关判断；它不能由 403 推断 Pod 不存在、Pod 正常或已修好权限。**部分证据可用，不意味着整项诊断证据完整。** S05-2 没主动强调 fixture；教程明确补充这是合成数据，不能包装成生产日志经历。

### 第三步：为什么没有红色 Error，任务仍然失败

打开 **S06-1 → Tree → pods_log → Preview**。该原生 Tool 没有 Error 标记。展开输出的 **`0 → text`**：实际内容为 `ok=false`、`error_type=business_error`、`Synthetic log archive unavailable`。

点其父级 **`reader_outcome Warning`**：输入有 `tool_name`、`tool_call_id`；输出同时有 `wrapper_success=true` 和 `tool_outcome=business_error`。这说明外层调用返回了合法结果，但“取得日志”这个业务目标失败。

再点最后一个 **`ChatOpenAI → Preview`**。在 `pods_log` 的 Response 中可同时看到外层 `ok=true` 和 `result.ok=false`。模型确实看到了失败。最终回答承认日志不可用，仅依据成功的 Pod 详情说明 `Running` 与容器 `ready=false`、`CrashLoopBackOff`、重启 4 次可以并存，没有宣称知道具体崩溃原因。

练习自问：如果回答引用了“日志显示配置缺失”，应给 FAIL，因为该 Run 从未拿到日志。不能把 S05 的证据搬到 S06。

### 第四步：把调用与回执连起来

S06-1 的日志 Tool Call ID 是 `call_DFwHKjn1bE1RVGQy7q6DBRTE`。按以下顺序核对：

1. 首次 Generation 输出中的 `tool_calls[].id` 与参数。
2. `reader_outcome` 的 `tool_call_id` 与业务结果。
3. 后续 Generation 输入中同 ID 的工具回执。
4. 私有 State / History 中的 `ToolMessage.tool_call_id`。

原生 Tool Span 本身不保证直接携带 Call ID；本案例结合 Generation ID、工具名/参数/时间和 State / History 配对。报告的 `tool_call_proof` 与 `business_proof` 给出对应 observation ID，不凭相同名字猜测关联。

### 第五步：看耗时，不重复加总

在 S06-1 切换 **Timeline**；必要时点 `Show labels`。本次根 Trace 为 15.32 秒，两个 Generation 约 4.81 秒、10.29 秒，tools 父节点约 67 毫秒。这个样例的主要时间花在模型；第二次模型负责综合证据和生成回复。

`LangGraph` 包含 `llm`，`llm` 又包含 `ChatOpenAI`，所以父子耗时不能累加。并行工具也要看时间轴重叠。这里没有据此计算生产 P95，也没有把 Generation 总耗时当作首 Token 延迟。

### 第六步：对照本地报告

报告分开显示执行、工具、回答，附最终回答、逐条审阅依据、回答 SHA-256、真实 Thread / Run / Trace ID、Usage 来源与原始证据目录。`agent_review` 表示实施代理审阅，未调用 LLM Judge，也未写 Langfuse Scores；UI 的 Scores 为空是预期情况。

原始证据在活动目录的 `raw/S01-1/` 等子目录：`private.json` 保存 State / History / SSE / Run；`observations.json` 保存 API 观察；`result.json` 保存初始采集结论；`hashes.json` 校验原始文件。后续审阅和重新查询只产生新版本，不覆盖初始 UNKNOWN、STOP 或回答。

若你的 UI 缺少输入输出，先等待载入、展开字段，再与报告的 State / History 比对。仍缺失就记录 UI 缺失，不能把私有文件内容说成已在页面展示。

## 3. 复现入口与只读重建

在本案例实现分支的独立 Worktree 操作，设置唯一配置源的绝对路径。不要复制 `.env`，也不要在隔离 Worktree 的根目录或 `server/` 放第二份 dotenv。需要已有锁定 `server/.venv`、Docker、规定的 PG/Redis 缓存镜像和空闲端口 8000；预检不会安装、下载或停止别人的服务。

```bash
# 替换为本次指定的原工作目录根 .env；不 source 文件。
export OBS_LAB_ENV=/absolute/path/to/original-workspace/.env
make langfuse-case1-preflight

# 交付活动已用满 6 次。以下仅查询已有 Trace、生成新报告，不调用模型。
make langfuse-case1-report BATCH=case1-20261103-221120-c0624e06
```

报告命令输出 HTML 和 Markdown 的实际路径：`.local/observability-lab/case1/<活动>/reports/<版本>/index.html`。直接用浏览器打开 HTML，无需启动新 Web 服务。目录 0700、文件 0600；这些文件均不进入 Git。

未来主动开展新的付费学习活动时才执行下列命令；`new-activity` 本身不调用模型，随后每个场景最多发起两次 Run：

```bash
server/.venv/bin/python scripts/langfuse_case1.py new-activity
make langfuse-case1 SCENARIO=S01
# 先逐条审阅 S01 两条回答，导入审阅文件，再运行 S05。
make langfuse-case1 SCENARIO=S05
# 同样先审阅 S05，再运行 S06。
make langfuse-case1 SCENARIO=S06
```

每次 Run 最多 4 次模型决策、6 次工具调用，总超时 150 秒；SDK 原有重试上限保持不变。每活动限 6 Run、串行；重复场景被拒绝。故障目标未调用为 NOT_TRIGGERED，回答不合格为 FAIL，都不补跑。基础设施或摄取异常会停止后续模型调用。仅在未用槽位确实可继续且已审阅先前结果时，显式 CLI `--continue` 可以继续；它不会重放已预占槽位。

审阅文件是私有 JSON，key 为真实 Run ID，value 包含 `source=agent_review`、`status=PASS|FAIL`、`rubric_version=case1-v1`、`answer_sha256`、具体 `reason`。哈希使用 `obs_lab_verify.content_digest(final_answer)`，不要手工猜值或使用其他序列化算法。导入不调用模型：

```bash
server/.venv/bin/python scripts/langfuse_case1.py review \
  --batch <实际活动ID> --reviews /absolute/path/to/private-reviews.json
```

本版 review 导入专用于实施代理审阅，不可把真人评价伪标成 `agent_review`。复用时按 §2 的证据逐条记录；PASS 的依据要能回到对应 Run 的实际工具结果。

## 4. 三分钟面试讲稿

> 我做过一个 Kubernetes 诊断学习 Demo，用真实模型、合成 MCP 工具和本地 Langfuse 复现工具失败后 Agent 继续运行的情况。这是可复现实验，不是真实生产事故。
>
> 我设计了三个场景：正常查询、读取 Pod 被 403 拒绝，以及日志工具外层返回成功但内层业务失败。每个场景运行两次，总共六次，没有为了结果好看补跑。模型自主决定工具调用；正常场景的两次工具数量分别是四个和三个。
>
> 在权限场景里，我从 Tree 找到原生 pods_get Error，看到合成 403。然后查看业务观测和后续 Generation 的输入，确认错误确实进入了模型上下文。两次模型都继续生成回答，明确 Pod 详情不可用，只依据实际拿到的日志作有限判断，没有编造 Pod 状态或声称修复 RBAC。
>
> 业务失败场景更容易漏掉。pods_log 没有原生 Error 标记，但输出里面的 ok 是 false；reader_outcome 显示 wrapper_success=true、business_error。最终模型承认没拿到日志，依据 Pod 状态判断容器未就绪、处于 CrashLoopBackOff，同时保留具体根因未知。
>
> 因此我把结果拆成三层：Run 和 SSE 是否结束，工具是否真正取得证据，回答是否承认缺口并忠于证据。六次执行都成功，不意味着每次诊断都取得完整证据。合理的有限回答也可以通过回答质量评价。我用 Tool Call ID、Generation 输入输出和 State / History 交叉核对关联，并保存回答哈希和审阅依据。
>
> Timeline 还能辅助看关键路径。例如一条业务失败样例总共约十五秒，两个模型调用约四点八秒和十点三秒，工具父节点约六十七毫秒。我不会把父子 Span 加总，也不会用六条样本宣称生产 P95 或准确率。这套方法可用于生产排障的分层定位，但真实环境还需要脱敏、访问控制和更大规模评测验证。

## 5. 常见追问

| 追问 | 本案例支持的回答 |
| --- | --- |
| 为什么不能只看 HTTP 200？ | 它可以只说明模型 API 或工具协议请求成功。S06 的内层业务结果仍失败，必须看业务契约和证据是否取得。 |
| 为什么业务失败不一定是原生 Span Error？ | 原生工具未抛异常，合法返回了包含业务错误的数据。保留原生事实，再用明确的业务观测描述失败，不能把整条 Trace 强行染红。 |
| 工具失败、回答 PASS 能同时成立吗？ | 可以。S05/S06 的回答承认缺失、限定判断、没有编造事实。PASS 是本案例回答标准，不是任务证据完整或系统健康。 |
| 如何判断错误传给了模型？ | 查看失败后 Generation 输入中的同一 Tool Call ID、参数及回执，并与 State / History 核对；只看到工具报错还不够。 |
| 两个同名工具怎么区分？ | 首先用 Call ID，再结合 Generation、参数和时间；业务观测与原生 Span 的 ID 不是同一个概念。 |
| 403 要不要自动重试或扩大 RBAC？ | 本例只报告权限限制，没有扩大权限。是否重试要依赖错误分类和预算；权限拒绝本身不构成提升权限授权。 |
| 什么时候给 FAIL？ | 隐瞒 403、编造未取得的日志、把 Pod Ready 等同业务全好、声称已修复权限，或根因超过证据范围。未调用故障工具另记 NOT_TRIGGERED。 |
| Langfuse 自动保证答案正确吗？ | 不保证。它提供可观察证据；本次质量结论来自逐条 agent_review，未使用独立评审或 LLM Judge。 |
| 能作为生产经验说吗？ | 应说明是合成故障实验；可讲定位方法、证据分层和局限，不能编造真实事故、修复收益或线上指标。 |

## 6. 实施验收记录

实施基线 `d81d1588451821436c35ce0ef1614c59a7e73e3d`，Planning PR #102 已合并。Python 3.14.6、锁定 Aegra 0.10.8；本地现有 Langfuse v4.72.0 OSS。S01 使用 `issue12-blind-v1-phase-a2`，S05/S06 使用 `issue12-blind-v1-phase-b1` request metadata。

| Gate | 本次证据与边界 |
| --- | --- |
| G00 / G01 | 独立 Worktree、独立 API/PG/Redis/Mock；唯一原工作目录 `.env`；导出、API 查询和链接均为本地 Agent Lab；原工作目录未提交修改未动。 |
| G02 / G03 | 持久化预占 6/6，串行；实际模型、15 次客户端 POST、Run/SSE 和 Tool Call 配对可查。超时/重复/崩溃预算由离线测试覆盖。 |
| G04 / G05 | 四条目标故障实际触发且后续 Generation 可查；六份回答审阅都有来源、哈希和具体依据。 |
| G06 | 六条 Trace 已逐条 UI 核验，S05 Error、S06 内层错误/业务观测/后续 Generation、Timeline 与本文一致。 |
| G07 | 只读重建报告、转义、私有权限、哈希、旧 Japan 默认兼容均有定向测试；原始批次不覆盖。 |
| G08 | 本次范围 Ruff PASS，相关 pytest **272 passed**，diff-check、文档链接、私有文件权限、原始哈希与凭据值扫描 PASS；远端 CI 以 Implementation PR 实时状态为准，未执行前不算 PASS。 |

实际验证命令（独立 Worktree 的锁定环境）：

```bash
server/.venv/bin/python -m ruff check scripts/langfuse_case1.py scripts/case1_report.py \
  scripts/dev.py scripts/obs_lab.py scripts/obs_lab_verify.py scripts/obs_lab_reverify.py \
  scripts/obs_lab_score_upload.py scripts/compose_with_langfuse.py server/tests/test_langfuse_case1.py
server/.venv/bin/python -m pytest -q server/tests/test_langfuse_case1.py \
  server/tests/test_obs_lab*.py server/tests/test_dev_langfuse.py server/tests/test_dev_profiles.py \
  server/tests/test_dev_preflight.py server/tests/test_development.py
git diff --check
```

静态 HTML 生成和转义已测试；内置浏览器拒绝 `file://` 协议，因此 HTML 的浏览器视觉核验未运行。用户可以直接打开输出文件；本案例没有为此启动额外服务。六条 Langfuse HTTP Trace 页面核验均已完成。

未运行：真实 Kubernetes、Repair、LLM Judge、正式 Compose 部署和前端构建（无相关改动）。这些不是本案例验收范围。历史云端 Gate 不被本地结果替代。
