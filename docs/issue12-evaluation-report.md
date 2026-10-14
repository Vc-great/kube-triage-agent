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
| E06 Draft PR / 独立 Review | PENDING | 以远端实际状态补记 |
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

Fixture 束（按文件名和原始字节排序拼接）SHA256：`ea5f08d05452bb1ca03a89da6ba7608efc1c7874cddc0c317dfe7e4fadd28494`。离线命令结果：Ruff PASS；`pytest -q` 143 passed；Manifest PASS；`docker compose -p kube-triage-issue12-a/b -f infra/test.compose.yaml config --quiet` 两臂 PASS；8×3×2 dry-run PASS；`git diff --check` PASS。PR #22 的既有 CI 第 47 次运行 `success`；本 PR 的 CI 尚未触发。候选端口 12128/12129/13128/13129 的监听检查无占用；正式启动前仍需重查。

独立私有 `.local/issue12-a.env` / `.local/issue12-b.env` 已准备为 0600，模型配置相同、DB/API 凭据不同，使用实际 env 的两臂 Compose config 均 PASS。Host Docker 对这两个 project label 的只读容器/卷查询为空；沙箱内 Docker socket 拒绝访问不能作为 Host 状态证据。未启动 Compose、未发模型请求、未创建 Thread/Run、未碰真实 Kubernetes 或其他项目资源、未清理卷与旧资源。真实 Provider 兼容、服务端 effort、因果改进和人工结论均 UNKNOWN/NOT RUN。

私有配置只读预检显示模型 ID 为 `gpt-6-luna`，`LLM_BASE_URL` 是 HTTP 的 OpenAI 兼容端点；代码向 ChatOpenAI 请求 Responses API 与 High。内部 URL 与 Key 不进入本报告，Provider 真正接受及服务端 effort 仍须获批 Smoke 验证。A/B 私有文件的模型 ID、endpoint、Key 相同，端口与 DB/API 凭据独立。
