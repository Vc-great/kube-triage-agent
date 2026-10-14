# Issue #12 评估报告（离线、Smoke 与正式 A/B）

状态：**真实 Provider A 臂 Smoke 1/1 PASS；正式 A/B 48/48 Run 完成、24 组配对完整；人工质量结果 PENDING**。Run 成功及规则证据齐全不等于诊断正确，当前不能推断 B 优于 A。

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
| E07 Provider Smoke | PASS | 获批后经验证 TLS 与 SSH 回环隧道执行 A 案例 a 的唯一 Run；详见文末实测记录 |
| E08 同分母 A/B | 运行完成 / 质量 PENDING | 获批后 A/B 各 24 Run，24 组配对完整；客观结果见文末 |
| E09 人工质量评分 | PENDING | 48 条事实预填已保存私有文件；由用户本人逐案评分 |

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
| F07 PR CI / 独立 Review | CI PASS / Review BLOCKED | P1 修复 Head `6471482` 的 CI #51 Python/Web/Compose PASS；GitHub 暂无独立 review。 |
| F08 Provider / A/B / 人工 | Smoke PASS / A/B 已运行 / 人工 PENDING | 后续独立授权的 A 案例 a 单次 Smoke 与 48 Run 均已完成；真人评分未填写。 |

冻结 Prompt SHA256：A=`37cb77f6f971b9c932f067711ceee9d9a17f97e47b012d4cc2163208bc1e2cc7`；B=`3915b88e6c1f9643b2fcab5c8a1c8c6f62addeb6c0c9e1f4a49ee6b039031566`。两次 dry-run 分别只规划 A Smoke 1 Run 与正式 A/B 各 24 Run，共 48 Run；均未读取私有 env、创建目录或访问 API。

P1-A 原复现：同名旧 Pod 的 Warning Event 带有与本次目标 `pods_get` 明确不等的 UID，旧 `inspect()` 会把它记作 `target_event_weak`。现仅 UID 相等才为强证据；冲突事件 `event_uid_mismatch=1` 且不贡献证据；没有可信目标 UID 时只记未核实弱线索。P1-B 原复现：Aegra `success` 且 SSE `end`，但 Tool Call ID 错配或 namespace 越界时，旧主循环仍可能标 Run success 并继续后续请求。现由 `run_outcome()` 明确分类并停止；私有 State/History/Runs 可回取时保留，摘要记录已尝试与未执行分母。流中断后的 SSE 原始增量无法从旧 `stream_run()` 复原，记 `UNKNOWN`，不伪造。

同类边界补强：Graph 的 Provider/MCP 异常答复可能伴随 Aegra `success`，现会停止后续 Run；真实预算终止记失败但不误当 Provider 故障，超过 4 次决策或 6 次工具调用则作为预算违约停止。模型响应元数据如明确回显其它模型 ID 也停止；无回显时保留 `UNKNOWN`。

离线修复交付时的配置边界：两臂私有 env 为 0600，Provider endpoint 属**私有网段 HTTP**，当时未证明受保护传输。Runner 在创建 Thread 前拒绝非回环 HTTP；须经 TLS 验证的 HTTPS 或回环代理及重新预检。完整 endpoint、Key、Token 未公开。下述 Smoke 使用了临时受保护传输配置；原两臂 env 仍不能直接用于正式 A/B。

## 2026-10-14：获批的 A 臂单次 Smoke

用户在上述离线修复交付后单独批准继续。原私有端点无可验证 TLS；本次仅为 A Smoke 派生了忽略的 0600 私有配置，以容器内校验的临时 HTTPS 地址接入本机回环 TLS 桥接，再经 SSH 隧道抵达同一 Provider 后端。无凭据的容器内探测返回 401；实际 API 容器确认 `test`、Prompt A、`gpt-6-luna`、Responses High 请求、Mock-only Reader、冻结数据集与 Repair 禁用。原两臂 env 未改，正式 A/B 仍须独立授权和运行时复核。

Docker VM 曾因空间不足使本次 A 项目的 Redis/Postgres 无法初始化；只清理了当前 Buildx builder 中超过 24 小时、未使用的构建缓存，释放约 8.5GB，未删除镜像、容器或卷。初次 Runner 命令被主机默认 Python 3.9 在创建 Thread 前拒绝，未发送数据；使用仓库现成 Python 3.14 环境后才执行唯一 Run。

私有输出目录 `.local/eval-runs/issue12-smoke-a-20261014-1418/` 为 0700，四个证据文件均为 0600。A 案例 a、repeat 1：Aegra Run `success`，耗时 18.473 秒；模型元数据回显 `gpt-6-luna`，4 次决策、4 个 Tool Call 与 4 个成功 Mock ToolMessage 一一配对，工具选择合规且无无关调用，目标 Pod 状态、容器状态、目标 Event 和日志证据齐全。Token 使用量为 input 5792、output 610。Responses High 仅是请求配置，服务端实际 effort 为 `UNKNOWN`。主观诊断正确性与因果过度推断仍 `PENDING`，不以客观规则结果代替人工评分。

已停止本次 A 项目容器和临时回环传输，保留其独立卷与镜像；B 项目未启动，正式 48 Run 未创建。未触碰真实 Kubernetes、既有 Compose 项目或旧卷；PR 保持 Draft，Issue 保持 Open。

## 2026-10-14：另行获批的正式 48 Run

用户在 Smoke 交付后另行批准下一轮。使用同一 Provider 后端、`gpt-6-luna`、经容器校验证书的临时 HTTPS/TLS 桥接与本机 SSH 隧道；A/B 两臂的模型、Key、Responses High 请求、Graph、四个只读 Tool Schema、Mock 数据集及问题文本一致，只有 test-only Prompt 变体不同。A=`kube-triage-issue12-a`、B=`kube-triage-issue12-b`，各自独立 Postgres/Redis 卷、API 凭据和 12128/12129 回环端口。两臂运行时环境、Graph/Prompt/Mock 代码 SHA 与私有配置核对通过，两个 Mock 镜像内的 Fixture 束 SHA 均等于冻结值；`REPAIR_ENABLED=false`，Reader 仅接 Mock。运行使用仓库现成 Python 3.14；Runner 在 git `1d4cae1` 上执行，冻结盲样、Fixture 束、Prompt A/B 和 Graph SHA 与本页既有记录一致。

私有目录 `.local/eval-runs/issue12-formal-20261014-1435/` 为 0700，原始逐条轨迹、`runs.json`、`summary.json`、`reviews.json` 均为 0600。8 案 × 3 次 × A/B = **48/48 Run**，A/B 各 24/24，24 组 `(case, repeat)` 均配对；未执行数 0，提前停止原因为 `none`。48 个 Thread ID 与 48 个 Run ID 均唯一；Aegra Run、SSE、State/History 的 Runner 规则均判成功。48 条模型元数据均回显 `gpt-6-luna`，且 Tool Call/ToolMessage ID 配对、工具选择、Mock 成功回执、规则所需证据和最终答复均通过；工具失败、无关调用、预算超限、模型身份不符和 Provider 不兼容计数均为 0。High 仍仅是请求配置，服务端实际 effort 为 `UNKNOWN`。

| 客观指标 | A | B |
| --- | ---: | ---: |
| 计划 / 成功 / 有效轨迹分母 | 24 / 24 / 24 | 24 / 24 / 24 |
| 规则证据齐全 | 24/24 | 24/24 |
| 延迟中位数（秒） | 16.8415 | 18.1595 |
| 延迟最小–最大（秒） | 12.182–23.709 | 12.560–23.465 |
| 总 Token 中位数 | 5970.5 | 6157 |
| 总 Token 最小–最大 | 4725–8129 | 5565–8360 |
| Tool Call 总数 / 失败数 | 88 / 0 | 87 / 0 |
| 重复同参工具调用 | 1 | 0 |

配对的 B−A 延迟差中位数为 +1.235 秒，总 Token 差中位数为 +414.5；24 组中 B 的延迟和 Token 分别有 18 组较高。这些是描述性运行指标，不是诊断质量改善的证据。唯一重复调用在 A 案例 a 的第 3 次 Run，重复了同参 `pods_log`；Runner 将其保留为质量观察，未触发协议硬停止。

`reviews.json` 的 48 条主观字段仍全为 `PENDING`。私有 `human-review-facts.json` 另行预填了每条问题、模型答复、模型当时收到的 ToolMessage 内容与 ID、独立 Ground Truth 和规则证据，供用户本人逐案填写判断、理由、评分人与时间；Codex 未代评。正式运行后已停止 A/B 容器及临时回环传输，保留独立卷与镜像；未触碰真实 Kubernetes、既有 Compose 项目或旧卷。PR 继续保持 Draft，Issue 继续 Open。

## 2026-10-14：48 条人工盲审材料准备（质量仍 PENDING）

本次只读复核了原有 `runs.json`、`summary.json`、`reviews.json`、`human-review-facts.json` 与 48 份私有 State/Run 快照：A/B 各 24 条，24 个 `(case_id, repeat)` 配对完整，Thread/Run ID 各 48 个唯一；每条事实中的问题、完整回答、ToolMessage ID/内容与原始 State 一致，独立 Ground Truth 与冻结盲样一致。盲样、Fixture 束、Prompt A/B 的四组冻结 SHA 均未漂移；Graph SHA 为 `fe0c6503b03a09d6cff9034530750d726c3132be342a4c6ec4399d298ac4ffec`。运行记录统一指向执行时 Git `1d4cae1`、模型 `gpt-6-luna`；服务端实际 reasoning effort 仍为 `UNKNOWN`。

从这些既有事实生成了私有的 `review/blind-review-forms.json`（48 条）和隔离的 `review/blind-id-map.json`，另有 `review/review-handoff.md` 与源文件 SHA 清单，均位于原正式运行目录下，目录权限 `0700`、文件权限 `0600`，受 `.gitignore` 排除。审阅表以不透明编号打乱，隐藏 A/B、case/repeat 到臂的映射和 Prompt；保留问题、完整回答、模型当时所见 ToolMessage 与独立 Ground Truth、禁止断言。此为**审阅者对 A/B 分组盲**，不是隐藏题目或 Ground Truth 的双盲实验。Event UID 相等、缺失、冲突分别按强证据、弱线索、非目标证据解释，独立查询不得冒充模型所见。

48 条 `diagnosis_correct`、`grounding_score`、`false_positive`、`causal_overclaim`、`tool_error_handling` 及理由、审阅人、审阅时间仍全部 `PENDING`。状态为 `REVIEW_REQUIRED / HUMAN_REVIEW_REQUIRED`；只有用户本人逐条核对证据、填写并确认后，才可校验评分、解盲并计算描述性的 A/B 配对质量结果。现阶段 **QUALITY=PENDING**，不能断言 B 优于 A，也不自动采用 B Prompt。

本次离线检查：Ruff PASS；`pytest -q server/tests` 155 passed；Manifest PASS；A/B Compose `config --quiet` PASS；正式 48 与 Smoke 1 的 `--dry-run` PASS；`git diff --check` PASS。Compose 首次未传私有 env 时因必填变量缺失而报错，补用既有受限 env 文件仅执行 `config --quiet` 后通过；没有启动容器。原 PR Head `cb8b72e` 的 CI #53 Python/Web/Compose 均通过，GitHub 无正式独立 Review。新增 Provider/Thread/Run、Kubernetes 写入、Docker 资源清理均为 0；PR 保持 Draft，Issue #12 保持 Open。
