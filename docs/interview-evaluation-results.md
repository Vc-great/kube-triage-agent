# 一次真实的 Agent 评测：多加一句证据约束后，为什么分数反而降了？

先打开[本地双版本 Compare](http://localhost:3000/project/agent-lab/experiments/results?baseline=ad3bd8f3-e7cd-57d3-bc2d-b41bc0809ea6&c=a72162b8-4c8e-5959-a0b7-8772937ed4a4)。2026-11-04 在本地 Agent Lab（Langfuse 4.72.0）用同一个三题 Dataset 完成了两组真实实验。每版各 3 个新 Thread，合计 6 个 Agent Run，真实模型为 gpt-6-luna，工具查询对象为合成 Mock。Judge 尚待学习者独立标注及单独授权。可先读[架构图与纸面练习](plans/issue-92-interview-evaluation.md)，再用本文检查纸面假设是否在实际运行中出现。

**观察结果**　候选版在 S06 的 grounding_rule 从 PASS 变为 FAIL。实际回答明确说明日志不可用、具体崩溃原因无法确定。按现有词表复算能重现 FAIL，按证据复读则发现一个同义表达漏判。三个样本不足以支持切换默认 Prompt，暂时保留基线，优先校准这条评分规则。

## 从一张表读懂本次变化

Baseline 使用原 System Prompt。Candidate 仅增加“仅依据本轮成功取得的证据作出诊断，明确说明缺失证据。”两版用相同模型配置、问题、fixture、工具白名单与每 Run 预算。已核验六个不同 Thread、Run 和 Trace 的映射、实际 Generation 里的系统指令、Compare 中的输入与最终输出。运行代码为 `da74df8`，规则为 `obs-lab-rules-v1`。两个失败场景题面相同，网页中用 Item 的 metadata.scenario 区分它们。

| 实际题目 | 基线 Trace | 候选 Trace | 执行与证据 | grounding_rule |
|---|---|---|---|---|
| S01 正常查询 | [S01 A](http://localhost:3000/project/agent-lab/traces/d8286ac77e572312eacbc698932c8e01) | [S01 B](http://localhost:3000/project/agent-lab/traces/019d2dc26910d0560f59f22567e30aa2) | 两版均 4 次模型决策、3 次工具成功 | PASS → PASS |
| S05 Pod 详情权限拒绝 | [S05 A](http://localhost:3000/project/agent-lab/traces/a4556aebf7a74f2a882e6e07f63dec9a) | [S05 B](http://localhost:3000/project/agent-lab/traces/20f28561b2a13ff10fcb42ad47aed37f) | 两版均触发拒绝，另有一次成功回执，各 2 次模型决策 | PASS → PASS |
| S06 日志不可用 | [S06 A](http://localhost:3000/project/agent-lab/traces/3b34d391538b0da16bc10aa2897cc0bd) | [S06 B](http://localhost:3000/project/agent-lab/traces/08a8faf1e723d4d73e70356bf96b3ba8) | 两版均取得 Pod 详情、触发日志业务失败，各 2 次模型决策 | PASS → FAIL |

| 每版分母均为 3 题 | 基线 PASS / FAIL / UNKNOWN（适用） | 候选 PASS / FAIL / UNKNOWN（适用） | 每版不适用 |
|---|---|---|---|
| tool_protocol_valid | 3 / 0 / 0 | 3 / 0 / 0 | 0 |
| fault_handled | 2 / 0 / 0 | 2 / 0 / 0 | 1，S01 没有注入故障 |
| grounding_rule | 3 / 0 / 0 | 2 / 1 / 0 | 0 |
| evidence_uid_matched | 0 / 0 / 0 | 0 / 0 / 0 | 3，本次没有可用于该规则的目标 Warning Event |
| unnecessary_retry | 0 / 0 / 0 | 0 / 0 / 0 | 3，本次未识别出同参重复 |

Scores API 使用分类 UNKNOWN 承载“不适用”，comment 保存 applicable=false。网页可能显示故障处理 PASS 2/3，按适用样本计算是 2/2。面试中先讲分母，再讲比例。

## 在网页自己定位一次失败

1. 打开上方 Compare，核对 Baseline 为 interview-ab-v1-baseline，右侧为 interview-ab-v1-candidate，表头为 3 items。看 grounding_rule 的 3/3 与 2/3；以每题每列的 Score 定位发生变化的那一格。
2. 打开 S06 B。Tree 选择 pods_log，读内层业务回执；再点后续 ChatOpenAI 的 Preview，确认输入里收到了日志不可用。核对成功的 pods_get 回执，看它足以支持哪些有限结论。
3. 回到最终回答，按三类断言做标注：容器未 Ready 且 CrashLoopBackOff 有 Pod 证据，日志不可用有失败回执，具体根因仍待确认。词表第二组要求命中“未知 / 无法确认 / 不能确定 / 证据不足”，这个回答写的是“无法确定”。原始规则结果保留。这里的解释是代理复盘，人工质量分仍为 NOT RUN。
4. 学习者自行分别记录 S06 A 和 B 的“断言、对应回执、遗漏的可用证据、PASS/FAIL/UNKNOWN、理由”。两版标注完成后才引入 Judge，先用分歧案例检查评分口径。如果要改词表，升规则版本并对相同六份回答离线重评；无需为了验证评分器而再次调用诊断模型。

## 本地怎样复算

本机私有活动保存在实施工作树的 `.local/observability-lab/interview-v1/interview-ab-v1/`。activity.json 记录版本与预算占用，raw 保存取证，report.json 记录每条规则理由和适用性，score-readback.json 记录已核对的上传批次。以下命令要求已有本地项目访问权与对应的已保存活动。

```sh
# 从本实验工作树根目录运行；ENV_FILE 指向获准的私有配置文件。
server/.venv/bin/python scripts/interview_eval.py verify --env-file "$ENV_FILE"
server/.venv/bin/python scripts/interview_eval.py verify-scores --env-file "$ENV_FILE"
```

verify 只读 Langfuse 和已有执行证据，重建本地派生报告；verify-scores 仅 GET 既有 30 个 ID。首次 Score 写入后的核查遇到微秒时间戳被本地服务存成毫秒，保留了原 journal，按服务端的毫秒精度逐条核对，其余字段与 Trace 关联完全匹配。六次 Run 和一次批量 Score POST 已完成。

首次在有新预算的独立环境部署时依次使用 sync、run、verify，最后 scores 需要操作者核对刚生成的精确计划哈希。sync 针对固定 Item ID 回读，已存在的内容不匹配会停止；run 预占每题每版唯一槽位，失败或摄取延迟保留该槽位；本次活动不再运行模型。实验上下文在隔离的 API 进程通过既有 Aegra exporter 随同真实 Graph、模型与工具 Span 导出。[Langfuse 的 OpenTelemetry 实验契约](https://langfuse.com/docs/evaluation/experiments/experiments-via-opentelemetry)
