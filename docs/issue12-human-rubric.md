# Issue #12 真人审阅模板

每个 A/B、case、repeat 分别复制一份并由用户本人填写。初始状态全部 `PENDING`，规则轨迹或 Aegra `run_status=success` 不代表诊断正确。

| 字段 | 待填值 |
| --- | --- |
| arm / case_id / repeat / Thread / Run | PENDING |
| diagnosis_correct（0/1） | PENDING |
| grounding_score（0/1/2） | PENDING |
| false_positive（0/1） | PENDING |
| causal_overclaim（0/1） | PENDING |
| tool_error_handling（0/1/NA） | PENDING |
| 判断理由与禁止断言核对 | PENDING |
| 对应 ToolMessage ID 列表 | PENDING |
| 模型当时看到的证据摘录及私有文件位置 | PENDING |
| 独立 Ground Truth 对照及盲样版本 SHA | PENDING |
| 审阅人、评分时间 | PENDING |

`reviews.json` 由 Runner 为每个 Run 生成同字段私有模板。人工检查原始 ToolMessage 后填写；禁止把独立 Ground Truth 或管理员事后观察补进模型当时可见证据。Issue #11 H/C/I 表格是独立任务，不搬作本实验分数。
