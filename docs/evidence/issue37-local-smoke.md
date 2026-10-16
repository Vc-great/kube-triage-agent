# Issue #37 本地脱敏观察记录

日期：2026-10-16。仅隔离 Compose `kube-triage-issue37-timeline`、Fake Model、Mock MCP、浏览器 Agent Chat。API `127.0.0.1:12437`，Web `127.0.0.1:13437`，Postgres `15437`，Redis `16337`，Mock MCP `18437`；独立数据卷 `issue37_postgres`、`issue37_redis`。本记录是观察摘要，不包含完整 SSE、Token、Pod Log 或认证头。

## Gate 0 与 Reader

真实 Aegra Run 的事件顺序含 `metadata → values → custom → messages → values → end`。`custom` 的安全字段形如：

```json
{"version":1,"type":"agent_progress","event_id":"<uuid>","stage":"tool","status":"started","label":"正在执行只读工具","tool_name":"pods_get","tool_call_id":"call_issue37_0","thread_id":"<thread-uuid>"}
```

前端 `@langchain/langgraph-sdk` 1.12.0 的 `onCustomEvent` 收到同一事件。浏览器在 `TOOL_DEMO` 看到正常正文 `Issue37 tool answer`、原 Tool Call/Tool Result 卡，以及 Timeline 的 `pods_get / 只读工具已完成`。打开 Hide Tool Calls 后原卡隐藏，Timeline 简要事件保留；刷新后原正文恢复，Timeline 消失。

Mock MCP SSE 观察（`tool_call_id` 与 ToolMessage 配对）：

```text
TOOL_DEMO  call_issue37_0: started → completed; ToolMessage=success; final=true; errors=[]
MULTI      call_issue37_0: started → completed; call_issue37_1: started → failed;
           ToolMessage={call_issue37_0: success, call_issue37_1: error}; final=true; errors=[]
MISSING    call_issue37_0: started → failed; ToolMessage=error; final=true; errors=[]
```

## Context Summary

合成 8 个已闭合历史轮次，Gate A 预算 6500；结果如下：

```text
Gate B off: custom=context trim completed → model started/completed → answer completed;
            summary_status=None; messages_events=21; summary_json_in_messages=False;
            final_answer_in_values=True
Gate B success: custom=context trim completed → summary started/completed → model started/completed → answer completed;
                summary_status=ready; messages_events=21; summary_json_in_messages=False;
                final_answer_in_values=True
Second run: custom=context trim completed → summary cache_hit → model started/completed → answer completed;
            no new summary started; final_answer_in_values=True
Invalid schema: custom=context trim completed → summary started/fallback → model started/completed → answer completed;
                summary_status=failed; messages_events=21; summary_json_in_messages=False;
                final_answer_in_values=True
```

浏览器在成功场景显示“历史上下文已安全裁剪、历史参考已采纳、模型已返回、答复已生成”；下一轮显示“沿用已校验的历史参考”。无效 schema 显示“摘要失败，已回退到安全裁剪”，正文仍为 `Issue37 final answer`，没有内部 JSON 文本。

## HITL

`REPAIR_SIMULATED=true` 的 Fake Repair 只读预检返回固定模拟 Deployment 0 副本；测试夹具令写函数直接抛错。浏览器展示原“离线模拟审批”卡；点击“拒绝”后，Resume 得到“审批拒绝或 proposal_id/参数无效；没有执行 Kubernetes 写入。”，审批卡消失。未测试批准、真实 Kubernetes 或真实 Provider。

## 历史测试波折

- 初次 Web 开发启动使用跨目录 `node_modules` symlink，Turbopack 不接受；改为在隔离 Worktree 本地复制既有依赖后 `pnpm build` 通过，未下载新依赖。
- 初次 Fake Summary 使用 2800 预算，Gate A 正确返回 `context failed`，没有正文；按仓库既有测试预算 6500 重测成功。
- 容器从 Tool 假图切 Summary 假图时配置路径一度仍指向 Tool 文件，Aegra 启动失败；修正临时配置后重测成功。
- 容器镜像初次尝试复用旧缓存时缺少依赖；按仓库 Dockerfile/锁文件重建隔离镜像后正常。

这些失败没有被算作最终通过，也没有覆盖或清理其他 Compose 项目及其数据卷。
