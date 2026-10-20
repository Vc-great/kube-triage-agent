# Issue #41 P0：离线 Provider Adapter/Contract 验收

本报告仅对应 [已合并 PR #56](https://github.com/Vc-great/kube-triage-agent/pull/56) 的 [权威设计](plans/issue-41-b1r-real-provider-contract-pilot-gate.md)。实施基线为 `4a946cd0befe25d27e680249adbb69a9960ed8a7`，独立 Worktree、分支 `ao/provider-contract/p0-adapter`。Issue #41 保持 Open；交付 Draft PR，不合并，不进入 P1/P2、B2/B3。

## 实现与边界

- 新增 `scripts/issue41_provider_contract.py`：不含真实 Transport 工厂、凭据输入、`--enable-live` 或 Provider 默认配置。唯一内置 Profile 是 `.invalid` 合成契约，Chat Completions、精确 HTTPS URL/Host/Path、TLS 必须验证、零 SDK retry。
- `ProviderProfile` 保存非秘密契约规范：Provider、Request/Echo Model、API、最大输出，以及 tokenizer、reasoning、Usage、带日期的价格/币种、失败计费、上游重试和 Provider 支出硬限额的证据引用。未知值为 `None`；填写证据引用不能使 `live_gate()` 从 BLOCKED 变为 GO。
- PR #55 Runner 只增加可选 Adapter 接口和模型构造参数；未传 Adapter 的默认配置不变。新旧 CLI、两张原 Graph、冻结 Manifest、Mock Reader、`Budget.reserve/receipt`、原始回复检查、Tool ID/UID 回执、安全评分、私有输出和盲审模板均复用。
- 每次模拟 HTTP 发送前同时预约单 Run/全局 attempts、合成 Token、合成费用；无 await 间隙，不退额度。并行请求拒绝，HTTP 错误/超时/缺失或异常 Usage/模型回显错误立刻锁定 STOP，后续 SDK retry 或 Run 不可发送。Profile 禁止 retry；专项还故意把 SDK 配为 retry=1，验证错误不能绕过 STOP。原 Runner 的重试预约回归测试保留。
- 仅精确 `httpx.MockTransport` 可进入 Adapter。客户端固定 `trust_env=False`、`follow_redirects=False`，禁 streaming、多生成、Responses、reasoning 参数和额外工具；OFF 为四 Reader，ON 额外允许原 `write_todos`。原始恶意正文即使附合法 Tool Call 也在 Graph 兜底前检查；失败前真实执行过的合成回执保留。
- CLI 清空继承环境、禁 Python socket/DNS、禁 Trace；本地验收额外用 macOS `sandbox-exec` 的 OS `deny network*` 覆盖整个测试进程树。Python monkeypatch 不是 OS 安全边界；P0 的 Mock/TLS 配置测试也不是真实 TLS 握手或未来 Provider 出口白名单证明。CI 不声称已建立生产出口隔离。

## 实测环境与命令

2026-10-20，macOS arm64，CPython 3.13.14。`uv sync --frozen --offline --python 3.13` 复用 Host 安装与缓存，没有依赖下载/升级。冻结 `openai==3.29.0`、`langchain-openai==1.7.0`、`httpx==0.28.1`、`deepagents==0.7.28`。

以下命令工作目录为 `server/`；私有临时输出使用解析后的绝对路径，不能含符号链接、不能覆盖已有目录。测试临时文件不作为 PR 附件。

```sh
uv run --frozen --offline ruff check src tests ../scripts/dev.py ../scripts/compose_with_langfuse.py ../scripts/eval_issue12.py ../scripts/prepare_issue12_blind_review.py ../scripts/summarize_issue12_human_review.py ../scripts/eval_phase3a.py ../scripts/check_issue11_manifests.py ../scripts/issue41_b1r_pilot.py ../scripts/issue41_provider_contract.py
sandbox-exec -p '(version 1)(allow default)(deny network*)' .venv/bin/python -m pytest -q
.venv/bin/python ../scripts/check_issue11_manifests.py
```

CLI 实跑均放在同一 OS 禁网策略下：

```sh
.venv/bin/python ../scripts/issue41_b1r_prep.py --dry-run
.venv/bin/python ../scripts/issue41_b1r_pilot.py --offline-readiness --simulate-budget --output <new-absolute-private-path>
.venv/bin/python ../scripts/issue41_provider_contract.py --offline-contract --simulate-budget --output <another-new-absolute-private-path>
```

## Gate

| 项目 | 结果 | 证据与限制 |
| --- | --- | --- |
| 规划/基线/范围 | PASS | #56 merge commit 等于实施时最新 main；无正式 Agent、Graph、依赖、冻结数据修改 |
| 原离线行为 | PASS | dry-run 24 槽；原 readiness 4 槽/12 次模拟 HTTP；新 CLI 默认 0 额度、首槽 STOP、零发送 |
| 候选 Adapter/冻结 SDK | PASS（离线） | 四槽/12 次模拟 HTTP；精确请求端点、模型、Tool schema 与参数断言；TLS 禁降级、端点/重定向/多生成/Responses/额外工具负测 |
| 预发送预算与 STOP | PASS（合成） | 单 Run/全局 0/1/耗尽、Token/费用预约、429/500/连接失败/超时、重试、并行负测；失败无退款且不能下一槽 |
| 原始安全证据 | PASS（合成） | 恶意正文+合法 Tool Call 拒绝；读取后失败保留 3 条 Reader 回执及原顺序、Tool ID、旧/新 UID；R05 未核验状态保留 |
| 私有输出/隔离 | PASS（本地 P0） | 0700/0600；恶意继承环境不激活 Provider；子进程 loopback connect 被 OS 以 EPERM 拒绝；所有实跑 Provider/K8s 请求=0 |
| 冻结输入/顺序 | PASS | Manifest SHA `fbd010f8fa61847efe05f84a98d1991b4ef238ea43cba20c82eecef79155df1f`；4 Pilot 槽独立 Thread；余 20 槽不运行 |
| Ruff/pytest/manifest | PASS | 与 CI 一致的 Ruff 文件集通过；OS 禁网下 `585 passed in 54.70s`；3 个 Pod manifest 检查 PASS |
| CI/独立 Review | 待最终记录 | PR checks / AO 独立 Reviewer；未出结果前不标 PASS |
| 真实 Provider/费用/Tokenizer | BLOCKED / UNKNOWN | 没有批准或可核对真实契约；合成 INPUT=65536、OUTPUT=512、RATE、SYNTHETIC 币种均不是实际 Token/账单保证 |
| B8 / 真实 Kubernetes / 真人盲审 | NOT RUN | 没有真实调用、真实质量或 Planning 因果收益声明 |

## 继续前必须解决的未知项

实际 Provider、HTTPS Host/Path、Request/Echo Model、tokenizer 或服务端输入硬限制、输出是否包含 hidden reasoning、缓存及 Usage 语义、带日期的价格与币种、失败计费、CPA/网关上游重试和独立账单均未验证。实际 Usage/费用始终 UNKNOWN；预留数额不等于已计费，超时不能记为免费。

后续需要用户另行决定并批准 Provider/模型/端点、合成数据传输范围、P1-A 探针或 P1-B Pilot 的独立许可、单 Run/全局 HTTP 尝试与 Token/费用额度、可承担最大暴露额、Provider 独立预付费或硬支出上限、测试窗口及 OS 出口白名单。仅有配置数字和证据字符串不构成授权。现有实现没有可解锁的 live 开关；未来真实 Transport 需要独立评审。无法建立可信费用上界则继续 BLOCKED，不放宽门禁。

回退：停止独立 CLI 或回滚本 PR；无服务、数据库、Checkpoint、Compose 或集群迁移。历史 A08=FAIL、Phase3B B06=FAIL、B2 阻断证据均保持。
