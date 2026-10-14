# Issue #14：离线指标验收记录

基线：2026-10-14 实时 fetch `origin/main=8de3394731e471673b47d689491b3ce2aba1b9bb`；Issue #14 OPEN；PR #24 已合并，原 Head `37fa04be01365e1692ae596af41ff527b88a8b76` 的 CI 成功。独立工作树从该 main 创建。历史 Golden、Phase 3A / Issue #12 原证据与 Graph/Reader/Repair 均未修改。

## 来源与结果

| 来源 | 私有原始记录 | State/证据可读 | 本期状态 |
| --- | ---: | ---: | --- |
| Phase 3A Mock | 0/12 | 0/12 | BLOCKED：原始 `phase3a-baseline` 目录未找到；不从历史报告合成逐条数据 |
| Issue #12 Mock A | 24/24 | 24/24 | PASS：离线再分析 |
| Issue #12 Mock B | 24/24 | 24/24 | PASS：离线再分析 |
| Real Kubernetes | 0 | 0 | NOT RUN / NO METRICS |

Issue #12 来源是既有 `.local/worktrees/issue12-evaluation-blind-ab/.local/eval-runs/issue12-formal-20261014-1435/`；本期仅只读。最终派生私有目录 `issue14-20261014-03` 受 Git 忽略。其 `metrics.json` 含完整内部 ID，未提交。以下为脱敏聚合，不把 Phase 3A、Issue #12 与 Real Kubernetes 混为同条件趋势。

| 指标 | A | B |
| --- | ---: | ---: |
| Run / 完整 Token 用量 | 24/24 | 24/24 |
| 总 Token（本批，含原生细分） | 150,906 | 160,345 |
| 已报告缓存读取 Token（主 Token 子集） | 27,648 | 30,720 |
| 已报告 reasoning Token（主 Token 子集） | 882 | 783 |
| Tool requests / received / 唯一匹配 | 88 / 88 / 88 | 87 / 87 / 87 |
| Wrapper success / error | 88 / 0 | 87 / 0 |
| Policy rejected / budget skipped / unpaired | 0 / 0 / 0 | 0 / 0 / 0 |
| P50 秒（Runner 端到端） | 16.8415 | 18.1595 |
| P95 秒（nearest-rank，n=24） | 22.548 | 23.220 |
| 模型/MCP 阶段耗时 | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN |
| 估算成本 / 实际账单 | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN |

这 48 Run 是 8 个合成场景、各 3 次、A/B 配对；P95 只是描述性样本统计。包装成功与正文结构检查不代表诊断正确；人工质量以 Issue #12 原确认记录为准，本期未重新评分。模型 HTTP attempt 与真实 MCP transport 调用分母均 UNKNOWN。#13 G03 保持 PARTIAL FAIL；L3 真实模型对抗 NOT RUN。

## 验收矩阵

| Gate | 状态 | 证据或缺口 |
| --- | --- | --- |
| K00 Repo/历史冻结 | PASS | 实时 main 与 Issue/PR 核验；改动仅本 Issue 新文件和 README |
| K01 Schema & provenance | PASS | 每 Run 数值的 unit/denominator/provenance，缺失 null+reason |
| K02 Token | PASS | 来源优先级、字段缺失、重复 ID、细分量、覆盖率测试 |
| K03 Tool | PASS | 唯一 ID、策略/预算/包装/结构分层；transport UNKNOWN |
| K04 Latency | PASS | median/nearest-rank；成功/失败分组；阶段 UNKNOWN |
| K05 Cost | PASS | 有效快照的虚构单测、严格 UNKNOWN 路径；本批无真实报价 |
| K06 Offline analytics | BLOCKED（Phase 3A）/ PASS（Issue #12） | 12 份原始轨迹缺失；48 份可读且只读再分析 |
| K07 Safety/compatibility | PASS | 旧 Runner/Graph 未改；无模型、Compose、Kubernetes 请求 |
| K08 Quality/CI | 本地与 CI PASS；独立 Review BLOCKED | 本地 Ruff、217 pytest、dry-run、Manifest、diff 检查 PASS；PR #25 的 CI #59 python/web/compose 均 PASS；该 CI Ruff 命令未包含新脚本，本地单独 Ruff 已覆盖。GitHub PR 无独立 Review，本轮不发起额外模型外发 |
| K09 Deliverables | PASS（Draft） | 中文设计/验收、私有指标、README 索引与 Draft PR #25；未合并、未关闭 Issue |

Issue #13 残余不可用本期 `wrapper_success` 或 `content_valid` 比率冲抵。未授权真实模型复测，因此真实 Kubernetes 的诊断质量与成本没有新结论。

Draft PR：[Issue #14：离线 Agent Metrics v1](https://github.com/Vc-great/kube-triage-agent/pull/25)。CI #59：[GitHub Actions](https://github.com/Vc-great/kube-triage-agent/actions/runs/38584685302)。独立 Review：BLOCKED（截至本次核验，无提交的 Review；不以 CI PASS 替代）。
