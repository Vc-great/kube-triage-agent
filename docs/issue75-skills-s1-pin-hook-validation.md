# Issue #75 S1：最小 pin-hook 与 Aegra 扩展点验证

> 2026-10-22；基线 `origin/main=d057b1e715740786800d474d101f4be57a6050a8`。
> [Planning PR #77](https://github.com/Vc-great/kube-triage-agent/pull/77) 已合并，权威 Gate 仍为[设计文档第 6 节](plans/issue-75-kubernetes-diagnosis-skills.md)的 S0–S9。
> **S1 STOP，S0–S4 未全部通过；本 PR 为离线实施 PoC 与证据，不是可运行的 Web Skills 产品。**
>
> 审阅后补充：公开 `build_graph` 现已在 SDK 装配前无条件抛出 `NotImplementedError`；不返回可恢复或可被后续注入 Checkpointer 的图。不安全原生装配移至 `server/tests/skills_probe_helpers.py`，仅用于保留反例和正向探针，应用包不包含它。该收口不实现历史来源认证，S3/S4 仍 FAIL，不靠拒绝全部恢复声称通过 Gate。
>
> CI修复补充：旧、新pin反例均由测试子进程执行原始安全断言并真实失败，父测试核对非零退出、精确计数和具体AssertionError；与公开builder的Fail Closed回归分开。测试套件通过表示“反例被保留且公开入口已关闭”，不表示不安全测试装配已满足S3/S4。历史失败结果不改写。

## 1. 范围与环境

- #77 已由 GitHub 确认 merged，合并提交即本轮 main；已读取 AGENTS.md、Issue #75、修订计划。#69/#72 仍 Open，main 的 #74 仅 Reviewer S1；无依赖其他 Worktree 的未合并实现。
- 当前独立 Worktree 从该 main 建立 `ao/diagnosis-skills/pin-hook-spike`；未修改其他 Worktree、正式 Graph、P0、Reader、Reviewer、HITL、Memory 或部署。
- Python 3.13.14，锁定 `deepagents==0.7.28` / `aegra-cli==0.10.8`，复用本任务已有冻结环境和本机缓存，不升级 SDK。
- 仅显式注入 FakeModel，合成 Reader、MemorySaver；探针子进程阻断 socket，关闭追踪。不调用真实模型/Kubernetes，不启动端口、容器、数据库或 Web。
- 内置三份 SKILL.md 继续来自只读包资源快照，精确路径与 SHA；无 StateBackend `files` 可信指令、Host FS、Shell、上传、子代理或 Repair。

## 2. 最小实现与已验证的边界

### SDK pin-hook

`ReadOnlySkillsMiddleware` 派生固定 SDK 的原生 `SkillsMiddleware`，保留同名 slot，只覆盖同步 `before_model` 与异步 `abefore_model`。非空或畸形 pin 直接拒绝，空列表不产生更新；不调用原生 pin 下载/插入方法。原生扫描、metadata 渲染、工具路由继续继承；原生 FilesystemMiddleware/read_file 不替换。

实际装配检查：唯一有效 Skills 实例、唯一 FilesystemMiddleware、六工具；无 Summary/Memory/SubAgent。正常三场景先见 metadata，经实际 read_file 后才见正文，问候不读取。验证了同步/异步 hook 的畸形输入，原攻击在 pin 节点被拒绝，合法 `input=None` Resume 成功，读取预算跨多次 Resume 保持两次，第3次为 error。按实际图节点枚举 before/after 暂停点，干净恢复与工具 ID 配对正例通过。

这些证明 **hook 扩展可用**，不代表已认证历史 Checkpoint 或已封闭全部客户端入口。

### Aegra 原生扩展点

`test_deep_diagnosis_skills_aegra_spike.py` 以真实 Aegra route、factory 分类/ServerRuntime、LangGraphService.get_graph、copy/with_config 和 auth handler 执行；仅替换 ownership DB lookup、Checkpointer/Store 和认证身份。HTTPX ASGITransport 直接调用应用，不开端口；不是真实部署/Postgres/SSE/worker 验收。

- factory 根据 **服务端** `access_context=threads.update` 抛出 HTTPException(403)。State dict/list/空字典、`values=null + as_node=__copy__`、checkpoint ID/dict、namespace 和伪造 access_context 均返回403。
- Profile 级 auth hook 可在 Thread metadata PATCH 和保留字段创建请求中返回403，未进行 DB 写入。
- 普通 GET State 与空值 POST 读取 shim 返回200；拒绝前后完整 head、State 与历史相同。
- Aegra 原生 copy 注入 MemorySaver 后，with_config/干净 Resume 成功；没有静默丢失持久化。

本轮 **13 passed / 35.33s**。测试中的 factory/auth 是未注册的最小探针，不是已交付的 Aegra Skills 入口，也不证明未来 facade、Run 输入、背景 worker 或所有写路径已安全。

## 3. 两个反例分别保留

### 旧 resume-pin：历史 FAIL，修订装配已拦住

旧装配的测试子进程仍执行原禁止模型调用断言，并真实触发 AssertionError：`model_calls=1`、`pinned_messages=3`、`native_read_file_calls=0`。父测试 `test_legacy_resume_pin_still_fails_safety_assertion` 只验证该旧失败继续存在；characterization 成功不能计作新安全 Gate PASS。新装配对同一攻击在 pin hook 拒绝，模型调用为0。

### 新 resume-consumed-pin：当前安全断言 FAIL，触发 STOP

最小顺序：

1. 使用旧原生装配与真实 MemorySaver，在 `SkillsMiddleware.before_model` 前暂停。
2. 用 SDK State 更新写入三项 pin；原生 hook 消费 pin，暂停在 `model` 前。
3. 此时三条 `lc_source=pinned_skill` HumanMessage 已持久化，`pinned_skills=[]`，模型尚未执行，下一节点明确为 `model`。
4. 在同一 MemorySaver 上重新构建 **新 pin-hook 测试装配**，执行 `ainvoke(None, config)`；审阅后此装配仅存在于 tests，公开 builder 不再返回图。
5. 新 hook 不会重跑已越过的 pin 节点；现有模型前检查仅看到 canonical metadata 和空 pin，放行旧正文。

实际结果：

```json
{"scenario":"resume-consumed-pin","model_calls":1,"pinned_messages":3,"pin_field_empty":true,"native_read_file_calls":0}
```

安全断言 `assert not model.inputs` 失败，未 skip、xfail 或改成“允许旧历史”。没有手工编造 read_file 成功消息或从 State 补全正文；pin HumanMessage 来自旧原生 hook 的实际执行。

公开入口关闭后，该未认证测试装配被归为显式历史characterization：`test_probe_consumed_pin_still_fails_safety_assertion` 要求子进程以该断言失败，并核对上述完整JSON。断言本身保留在`resume-consumed-pin`子进程；直接执行本节复现命令的子进程仍为失败。另有`public-reject-consumed-pin`用同一旧原生hook真实生成旧历史后调用公开builder，验证它抛出S1 STOP、无SDK装配/模型调用且head/State不变。不能以父characterization成功推断历史认证已修复。

复现（`server/`）：

```sh
uv run --frozen --offline python tests/test_deep_diagnosis_skills.py resume-consumed-pin
```

历史单独pytest执行结果：**1 failed / 49 deselected，2.09s**。上面的直接子进程命令在当前代码中保留同一失败。该证据是离线 Checkpoint 兼容/来源失败，不等于证明真实 HTTP 仍可绕过已测403的 factory，也不证明 SDK 必然无法实现最终方案。正确结论是 **最小 hook 替换单独不足以通过原 Gate**。

## 4. 逐 Gate 状态

| Gate | 状态 | 证据与限制 |
| --- | --- | --- |
| S0 | PASS（基线核验） | fetch、main/#77/Issue/依赖/独立分支已核对；原有859项回归均无失败，完整统计见第5节 |
| S1 | PASS（资源与原生解析） | 恰三份内置SKILL；SDK元信息、名称、路径及正文规范验证；wheel核验结果见第5节 |
| S2 | PASS（正常渐进加载轨迹） | 原生派生实例唯一，三场景实际read_file，问候零读取；不能外推旧历史可信，相关失败计S3/S4 |
| S3 | **FAIL** | 新pin hook拦住原攻击，ASGI写入口扩展点可用；但已消费pin的旧Checkpoint仍进入新模型。完整输入/历史来源/facade尚未建立 |
| S4 | **FAIL（旧历史加载旁路）** | 干净Resume和两次read_file预算、原Reader/Todo预算契约通过；旧Checkpoint仍带入三正文且没有实际read_file |
| S5 | NOT RUN | 无Skills Aegra配置/入口、真实Postgres、worker或服务；ASGI探针不代替此Gate |
| S6 | NOT RUN | 未启动Web，浏览器/真人未测 |
| S7 | NOT RUN（完整集成隔离） | 未进入S2；原有回归仅按第5节实际结果报告 |
| S8 | NOT RUN | 未做冻结ON/OFF评价或真实模型质量测试 |
| S9 | NOT RUN（最终可合并交付） | Draft证据PR；已知新安全负测失败，不宣称测试/CI全绿或就绪 |

## 5. 工程验证

- `uv run --frozen --offline ruff check src tests`：PASS。
- 最小SDK恢复专项：**8 passed / 40 deselected，14.31s**（新增同步/异步畸形pin及已消费pin测试前的首次结果，不能外推后续负测）。
- Aegra扩展点专项：**13 passed，35.33s**。
- `uv build --offline --wheel --python 3.13 --out-dir /private/tmp/kta-issue75-s1-wheel`：PASS；随后用标准库ZipFile核验wheel内技能目录恰三份SKILL.md、无额外资源、与源码逐字节相同。包文件是本轮临时构建验证材料，未纳入PR。
- `uv run --frozen --offline pytest -q`：**921 passed / 1 failed，312.56s**。原有859项全部无失败；新增63项中62项通过，唯一失败为`resume-consumed-pin`。这不是全量测试PASS，不具备进入S2或合并条件。
- `git diff --check`：PASS。原失败子进程的AssertionError保持，当前新安全失败也保持；未移除测试降低Gate。新安全测试失败意味着远端Python CI也可能失败；不能以“只是PoC”为理由改断言、跳过测试或放宽CI。
- 初始提交 `71e954d` 的[远端 CI run 39744552661](https://github.com/Vc-great/kube-triage-agent/actions/runs/39744552661)：FAIL。Web/Compose/Ruff/manifest检查PASS；pytest **918 passed / 1 failed / 3 skipped，406.97s**，唯一失败为相同的`resume-consumed-pin`，计数1模型/3pin/0read_file。
- [AO独立审阅](https://github.com/Vc-great/kube-triage-agent/pull/80#pullrequestreview-5613036721)要求来源边界未实现前builder不得接受可恢复Checkpointer。采用最小Fail Closed收口而不搭建框架：公开builder拒绝所有构图；不安全装配移到tests，旧新反例与合法Resume/预算探针仍运行，新增公开入口零装配验证。最新结果以PR的提交/CI/复审链接为准，不能沿用初始提交的结果替代新head验证。
- 审阅修正后针对两份Skills/Aegra测试运行：**63 passed / 1 failed，102.33s**；唯一失败仍为测试目录装配的`resume-consumed-pin`，禁止模型调用的断言未变。公开builder零装配测试通过；Ruff/diff检查通过。重新离线构建wheel，确认无`tests`/`skills_probe_helpers`，恰三份SKILL，应用模块无`create_deep_agent`调用。未重跑全量pytest，既有全量结果仍只归属于初始提交；S3/S4依然FAIL。
- CI修复后的核心专项：`uv run --frozen --offline pytest -q tests/test_deep_diagnosis_skills.py -k 'consumed or public or legacy'`：**4 passed / 48 deselected，7.84s**。两个子进程反例仍真实触发原断言失败，两个公开入口检查证明构图拒绝；没有skip/xfail、弱化原子进程断言或修改CI配置。全量结果在PR描述按当前提交单独报告；CI绿灯不解除S1 STOP。
- CI修复后的完整本地回归：`uv run --frozen --offline pytest -q`：**924 passed，255.59s**；`uv run --frozen --offline ruff check src tests`、`git diff --check` PASS。测试套件验证历史反例仍失败、当前公开入口已关闭；S3/S4所要求的可用安全恢复图未实现，相关Gate FAIL及S1 STOP不改写。

## 6. 最小替代方案与停止边界

本轮不继续搭建整套 Checkpoint 安全框架，不进入 S2。最小下一步应为单独的 **受控入口 + Checkpoint 来源绑定** Spike：

1. 复用已验证的 native factory/auth 扩展点，明确拒绝新Run的额外State/预置消息、State写入/派生以及Command更新/跳转；验证copy/with_config后不能绕过入口。
2. 只使用现有Checkpointer，先证明服务端建立的Graph/Thread/head/快照版本及Human轮次绑定，能区分新装配合法head和来源不明/旧pin历史；旧历史拒绝，原始历史只读保留。同修订干净Resume必须成功，不能拒绝所有恢复来换PASS。
3. 验证最小绑定/摘要在真实提交与取消/恢复时序中的一致性，包含pin字段已清空、marker伪造/移除、伪造read_file历史。仅扫描`lc_source`或比较hash不能认证来源；不能把客户端可写State/metadata当授权。

以上是待验证替代方向，**不是已完成的防护，也不修改已批准Gate**。若固定SDK/Aegra不存在足够小且可靠的提交/入口扩展点，继续STOP并报告，不升级SDK、不改正式Graph或引入新平台。本次没有实现版本绑定、摘要账本、密钥服务或全局状态框架。

回退为不导入本离线PoC模块；无Aegra注册需要撤销，无数据库/卷/旧Checkpoint迁移或清理。保持Draft，不合并、不关闭Issue #75；完整安全Gate未PASS前禁止将此图注册为Web入口。
