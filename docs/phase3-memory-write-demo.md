# Phase 3-1 私有 Demo 人工验收

**DEMO_WORKFLOW_ONLY**：同一 Demo API Key 可发起 Run 并自行批准；以下点击不能作为独立真人授权的安全证明。只在已隔离、无真实 K8s/MCP/LLM 连接的演示环境使用合成数据。启用需要 `INCIDENT_MEMORY_ENABLED=true`、`INCIDENT_MEMORY_WRITE_ENABLED=true` 及独立的服务端 `INCIDENT_MEMORY_PROVENANCE_SECRET`；不修改现有 `.env` 或 Compose 项目。

1. 用户本人打开 Web，使用专用 Demo API Key 新建 Thread，发送普通诊断并确认出现成功的 `pods_get` 工具回执。仅有文字报告、失败工具或旧轮证据时不应出现 Memory 卡。
2. 精确发送 `/remember-incident`，确认卡片显示 Pod、Namespace、UID、当时事实、根因未知、来源 Thread 与“历史参考、不是当前 Kubernetes 证据、不授权修复”。先在一条测试 Thread 点击 **拒绝**，确认无保存成功提示。
3. 在另一条有效诊断 Thread 再次发送 `/remember-incident`，由用户本人点击 **批准保存历史案例**。等待服务端返回 `stored`；仅卡片消失不代表写入成功。记录案例 ID。
4. 精确发送 `/forget-incident <案例 ID>`，确认出现独立撤销卡；先测试 Reject，再重发命令并由用户本人点击 **确认撤销**。确认返回 `revoked`，重复命令返回 `already_revoked`。
5. 记录本人操作的时间、Thread ID、候选/案例 ID、服务端状态及截图；不得把 SDK 自动 Resume 或 Codex 操作写成真人验收。若任何步骤出现未经批准写入、HTTP Store 直接篡改、Memory Resume 触发 Repair，立即停止演示并报告。
