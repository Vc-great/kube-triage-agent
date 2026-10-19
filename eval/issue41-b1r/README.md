# Issue #41 B1-R Prep（离线）

本目录仅用于 Prep。`cases.json` 中全部内容均为人工编造的合成数据；不引用集群、用户或历史运行数据。`manifest.json` 固定案例 SHA-256、seed、配对顺序与 24 个 Run 槽位。`python scripts/issue41_b1r_prep.py --dry-run` 通过已实现的 OFF/ON Graph 与进程内 Mock 调用执行 FakeModel 演练；脚本拒绝任何非 `--dry-run` 模式，不读取 Provider 配置，不发起 HTTP 请求，不连接 Kubernetes、Aegra、Langfuse。

R01–R04 对应既有 Golden 的四类故障/健康类别，但本清单使用独立合成目标与回执，不改写 `eval/cases.json`。R05 模拟旧/当前 UID 冲突及不可信日志注入；R06 模拟目标 Reader 403 与有限非目标 Event。固定 FakeModel 回答只用于协议、安全边界及降级检查，不是模型质量证据。

## 冻结方式

先校验清单 SHA 与 Manifest 中每个 Run 的 `case_id`、`replicate`、`pair_id`、`arm_order`。改变输入必须创建新版本并重新审核，不覆盖本版本。Manifest 用 seed `4101` 对 12 对 A/B 顺序进行一次性随机化；重复执行不会重新抽签。

- `manifest.json`: `fbd010f8fa61847efe05f84a98d1991b4ef238ea43cba20c82eecef79155df1f`
- `cases.json`: `b112ab33f3726742c9e36a9a5048053dc876c08b1bcc3e2725eef81a38e8336c`
- `rubric.json`: `214aec1158bb1d6c9480f97d6770fa6a2fcb2c267fc8fedb8cddfcd305fa4051`
- `human-review-template.csv`: `69c0611b6776e7b870c577d7f0a2efc83c198531edfd0884a90954ae708bcf0b`

## Gate 状态

- Fixture/Manifest SHA 与 24 配对槽位：Prep Runner 校验；固定产物随 PR 提交。
- FakeModel/Mock MCP 离线 Dry Run：只证明测试图在规定合成输入下的执行边界，不外推为真实 Provider 抵抗力。
- Pilot/Formal、Provider Usage/价格、云端 Trace、真人盲审结果：`NOT RUN`；需另行授权。

Pilot 授权至少要明确：模型/供应商与非敏感端点类别；4 个 Pilot Run 和总 HTTP 请求尝试数硬上限；总/单 Run 费用与币种；允许传输的数据仅限冻结合成数据；Langfuse/其它外传明确禁用或另行列明；测试窗口、超时/重试策略、隔离网络环境。Runner 本身不支持真实 Provider 模式。
