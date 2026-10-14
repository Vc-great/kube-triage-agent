# Issue #12 评估报告（离线阶段）

状态：**真实 Provider Smoke / A/B NOT RUN；质量结果 PENDING**。本页只记录代码与离线验证，不能推断 B 优于 A。运行报告生成器保留每臂计划/成功/失败、有效轨迹分母、配对记录数、延迟和 Token 分布；获批运行后据私有事实更新。

## E00–E09

| Gate | 状态 | 证据 |
| --- | --- | --- |
| E00 最新基线与 Issue | PASS | `origin/main=3f9ecee`；PR #22 merged；Issue #11/#12 open |
| E01 历史冻结 | PASS | `eval/cases.json`、四 Fixture、`docs/phase3a-report.md` SHA 见下；未改 |
| E02 独立盲样 | PASS | v1 8 案 + 无关 Warning Pod；数据集 SHA 见下 |
| E03 单因素与隔离 | PASS | test-only A/B；Luna Responses High 请求配置；四 Reader 未改 |
| E04 Runner / Rubric | PASS | 零请求 dry-run；私有输出路径防护；主观评分 PENDING |
| E05 离线回归 | PASS | Ruff、143 pytest、Manifest、A/B Compose config、dry-run、`git diff --check` 通过 |
| E06 Draft PR / 独立 Review | Draft PR PASS / Review BLOCKED | [PR #23](https://github.com/Vc-great/kube-triage-agent/pull/23) 已建；独立 Review 工具连接失败，GitHub 暂无 review |
| E07 Provider Smoke | BLOCKED / NOT RUN | 等候模型数据发送与 1 Run 授权 |
| E08 同分母 A/B | BLOCKED / NOT RUN | 等候 48 Run 授权 |
| E09 人工质量评分 | BLOCKED / PENDING | 无模型结果；由用户本人逐案评分 |

历史 SHA256：

- `eval/cases.json`: `3d399806f51215cd91db15b3c5d3e452906f26592893aa4e9438343f9347ea3b`
- `fixtures/crashloop.json`: `bbe5006200df1414726e8893c16c8997399fcb9efef406bf2cbb6fe650d79896`
- `fixtures/healthy.json`: `0b1ffc315786ea0ec744b8eb0edf40cc87cbef9e752c4898fcceb5f23c90a571`
- `fixtures/imagepull.json`: `4db8f6e8bbb603198846a4ccbd46f2c74109343638673e9a616e81e660712148`
- `fixtures/oomkilled.json`: `aa8ad85a1c4b4a351d407a84b354f7bb9b86b106db24b5ddc78400071bae52cc`
- `docs/phase3a-report.md`: `3a5c6550bf77a253b59ce779e3394ad3e693b218540cacf226fcfcda24d7a979`

数据集 `blind-v1.json` SHA256：`f29ffaf75af106562202b92ec34cc25a0025cd49ef7a924cbed0e6cdbfe9abe9`。原 Phase 3A 12/12 和 50/50 仍只属于历史四例，不作为本实验对照分母。Issue #11 H/C/I 人工评分仍 PENDING；首次 Luna M1、B06 和 Review BLOCKED 的历史结论保持原样。

Fixture 束（按文件名和原始字节排序拼接）SHA256：`ea5f08d05452bb1ca03a89da6ba7608efc1c7874cddc0c317dfe7e4fadd28494`。离线命令结果：Ruff PASS；`pytest -q` 143 passed；Manifest PASS；`docker compose -p kube-triage-issue12-a/b -f infra/test.compose.yaml config --quiet` 两臂 PASS；8×3×2 dry-run PASS；`git diff --check` PASS。PR #22 的既有 CI 第 47 次运行 `success`；[PR #23 初始提交的 CI #49](https://github.com/Vc-great/kube-triage-agent/actions/runs/38515924721) 已 success；本页状态更新提交后的 CI 须另核。候选端口 12128/12129/13128/13129 的监听检查无占用；正式启动前仍需重查。

独立私有 `.local/issue12-a.env` / `.local/issue12-b.env` 已准备为 0600，模型配置相同、DB/API 凭据不同，使用实际 env 的两臂 Compose config 均 PASS。Host Docker 对这两个 project label 的只读容器/卷查询为空；沙箱内 Docker socket 拒绝访问不能作为 Host 状态证据。未启动 Compose、未发模型请求、未创建 Thread/Run、未碰真实 Kubernetes 或其他项目资源、未清理卷与旧资源。真实 Provider 兼容、服务端 effort、因果改进和人工结论均 UNKNOWN/NOT RUN。

私有配置只读预检显示模型 ID 为 `gpt-6-luna`，`LLM_BASE_URL` 是 HTTP 的 OpenAI 兼容端点；代码向 ChatOpenAI 请求 Responses API 与 High。内部 URL 与 Key 不进入本报告，Provider 真正接受及服务端 effort 仍须获批 Smoke 验证。A/B 私有文件的模型 ID、endpoint、Key 相同，端口与 DB/API 凭据独立。

## PR #23 P1 离线修复复核（F00–F08）

| Gate | 状态 | 本轮证据 |
| --- | --- | --- |
| F00 基线 | PASS | 已重新 fetch；`origin/main=3f9ecee`，原 Worktree 干净、Head `3308e7c`，PR #23 Open/Draft、Issue #12 Open。 |
| F01 Event UID 三态 | PASS | 相等强证据；缺 UID/未核实 UID 弱证据；明确冲突事件不计目标证据，记录 mismatch。正反例覆盖两种工具顺序、错误回执和其它 Pod/Namespace/Kind。 |
| F02 协议/策略停止 | PASS | ID 缺失/重复/错配、非法工具/Namespace/额外参数、工具失败、模型身份不符及 Graph 转成答复的 Provider/MCP 失败均由纯函数判失败且停止；模拟 Runner 只创建 1 Thread，余 47 条 NOT RUN。 |
| F03 合法质量样本 | PASS | 证据不足或无关但合法工具不触发 hard stop；预算耗尽记失败，不当作正常结论。主观评分仍 PENDING。 |
| F04 数据冻结 | PASS | 盲样 `f29ffaf7…`、Fixture 束 `ea5f08d0…`，Phase 3A 历史 SHA 均未变化；Runner 对冻结数据/Prompt SHA 漂移提前拒绝。 |
| F05 单因素/模型配置 | PASS | A 原 Prompt、B 仅固定后缀；test-only；两臂模型、URL、Key、Responses High 请求与数据集一致。实际 Provider effort UNKNOWN。 |
| F06 离线验证 | PASS | Ruff、155 pytest、Manifest、A/B Compose config、1+48 dry-run、`git diff --check` 均通过；未启动服务。 |
| F07 PR CI / 独立 Review | CI 待最新提交 / Review BLOCKED | PR #23 既有 CI #50 PASS；本次修复推送后的 CI 须另核。GitHub 暂无独立 review；独立 Review 通道仍须单列。 |
| F08 Provider / A/B / 人工 | NOT RUN / PENDING | 本轮禁止模型发送。Smoke、48 Run 均未执行，真人评分未填写。 |

冻结 Prompt SHA256：A=`37cb77f6f971b9c932f067711ceee9d9a17f97e47b012d4cc2163208bc1e2cc7`；B=`3915b88e6c1f9643b2fcab5c8a1c8c6f62addeb6c0c9e1f4a49ee6b039031566`。两次 dry-run 分别只规划 A Smoke 1 Run 与正式 A/B 各 24 Run，共 48 Run；均未读取私有 env、创建目录或访问 API。

P1-A 原复现：同名旧 Pod 的 Warning Event 带有与本次目标 `pods_get` 明确不等的 UID，旧 `inspect()` 会把它记作 `target_event_weak`。现仅 UID 相等才为强证据；冲突事件 `event_uid_mismatch=1` 且不贡献证据；没有可信目标 UID 时只记未核实弱线索。P1-B 原复现：Aegra `success` 且 SSE `end`，但 Tool Call ID 错配或 namespace 越界时，旧主循环仍可能标 Run success 并继续后续请求。现由 `run_outcome()` 明确分类并停止；私有 State/History/Runs 可回取时保留，摘要记录已尝试与未执行分母。流中断后的 SSE 原始增量无法从旧 `stream_run()` 复原，记 `UNKNOWN`，不伪造。

同类边界补强：Graph 的 Provider/MCP 异常答复可能伴随 Aegra `success`，现会停止后续 Run；真实预算终止记失败但不误当 Provider 故障，超过 4 次决策或 6 次工具调用则作为预算违约停止。模型响应元数据如明确回显其它模型 ID 也停止；无回显时保留 `UNKNOWN`。

本轮配置边界：两臂私有 env 为 0600，Provider endpoint 属**私有网段 HTTP**，未证明受保护传输。Runner 已在创建 Thread 前拒绝非回环 HTTP，当前配置的真实 Smoke 为 **BLOCKED**；需要 TLS 验证的 HTTPS 或回环代理及重新预检。完整 endpoint、Key、Token 未公开。API 端口 12128/12129 无监听；两个 Compose project 的 Host 容器/卷只读核验仍需在实际启动前重做。离线代码可审查，当前运行配置尚未达到可发送模型数据的状态。
