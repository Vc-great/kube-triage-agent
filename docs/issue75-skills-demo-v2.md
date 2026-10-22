# Issue #75 Skills Demo V2：运行与验收

Refs #75。权威需求与 Gate 仍是 [V2 设计](plans/issue-75-kubernetes-diagnosis-skills.md)。
本文记录本 Implementation PR 的实际实现、启动方式与证据，不另立验收标准。

## 实现与边界

- 实施基线 `origin/main=4d7293831e8560ccff283a5c39ffaddd1125e8a2`（#82 已合并）。AO 创建的独立 Worktree，分支 `ao/skills-demo/v2`。
- 选择 **A：原生 `deepagents==0.7.28` SkillsMiddleware**。继承扫描、metadata 渲染、工具路由；仅以同名 slot 替换 pin hook，禁止主动 pin。原生 FilesystemMiddleware 执行实际 `read_file`。将 SDK 默认建议 `limit=1000` 的提示改为快照支持的 `limit=100`。
- 从 [#80 head 181638a](https://github.com/Vc-great/kube-triage-agent/pull/80) 原样取三份 `SKILL.md`，复用 SkillSnapshot、精确路径/读取预算和正常 FakeModel 验证思路；没有合并旧分支。公开 `build_graph` 现在返回可运行图。
- 独立 `aegra.phase-skills.json` 仅注册 `deep_diagnosis_skills`，入口只允许显式测试 FakeModel。恰六工具：四 Reader、`write_todos`、`read_file`。不增加 Shell、Subagent 或 Repair。
- 保持正式 `aegra.json`、Graph、Reader、HITL、Repair、Memory 与 Checkpointer 实现不变。正常完成的 Skills Thread 可继续普通多轮和重开历史。
- **不导入 #80 的旧 Skills Thread，不承诺旧 pin 或任意节点取消/中断后的恢复。** [#80 历史报告](https://github.com/Vc-great/kube-triage-agent/blob/181638a1812c6ebfd0a1ef2dc6881ec6106b9ef5/docs/issue75-skills-s1-pin-hook-validation.md)及 `resume-consumed-pin` 的 1 model / 3 pinned HumanMessage / 0 read_file 失败仍有效，未宣称修复。V2 未运行攻击专项。

## 最短启动

要求：Python 3.13、uv、Node/pnpm、Docker；依赖按锁文件准备。无需真实模型 Key、kubeconfig 或项目 `.env`。

```sh
cd server
uv sync --frozen --python 3.13
cd ../apps/web
pnpm install --frozen-lockfile
cd ../..
# 先确认本机没有此镜像；缺失时再获取。已有缓存不需 pull。
docker image inspect pgvector/pgvector:0.8.7-pg18-bookworm
# 仅在确实缺失时：docker pull pgvector/pgvector:0.8.7-pg18-bookworm
make dev-deep-skills-demo
```

打开 `http://127.0.0.1:13075`。表单 URL 为 `http://127.0.0.1:12075`，Graph ID 为 `deep_diagnosis_skills`，合成 API Key 为 `skills-demo-local-only`。它仅用于 loopback 测试，不是实际凭据。

启动器拒绝 server/Web 本地 dotenv，清理继承的模型/追踪/代理配置；只启动本次独立 PostgreSQL 容器（带 `ao.session` 标签）、Mock MCP、API 与 Web。端口默认 `15475/8000/12075/13075`；Reader `8000` 是既有白名单要求，冲突时停止，不杀已有服务。其他端口可用 `python3 scripts/skills_demo.py --api-port ... --web-port ... --db-port ...` 调整。日志写系统临时目录，Ctrl-C 仅结束本次子进程并删除本次容器/匿名卷。

依次点击“新 Skills Thread”并输入：

1. `诊断 Pod crashloop-pod CrashLoopBackOff`
2. `诊断 Pod oom-pod OOMKilled`
3. `诊断 Pod imagepull-pod ImagePullBackOff`
4. `你好`

前三例 Timeline 应先显示 `read_file` 和回执，再显示四 Reader，末尾中文观察/推断/UNKNOWN 引用 Tool Call ID 与 UID。问候无工具。保持 Hide Tool Calls 关闭；Skill 正文回执可展开。刷新/重新打开已完成 Thread，应保留普通消息；继续发 `上轮结论是什么` 可验证模型读到历史。不要使用工具消息旁的 Regenerate 来测试任意节点恢复，该能力不属于本期。

回退：Ctrl-C 关闭新 Profile，继续使用原有启动入口；不删除共享数据库、旧 Thread 或正式 Checkpoint。

## V2 Gate 记录

环境：macOS arm64 / Python 3.13.14 / deepagents 0.7.28 / aegra-cli 0.10.8 / Next.js 16.3.8 / pnpm 10.5.1。只用合成数据、FakeModel、Mock MCP 与临时 PostgreSQL；无真实模型/Kubernetes。

| Gate | 状态 | 实测证据 / 限制 |
| --- | --- | --- |
| V2-D0 | PASS | fetch 后基线 SHA 如上；已读 #75/#80/#81/#82；独立 Worktree，选择性复用，方案 A |
| V2-D1 | PASS | `uv build --wheel --offline`；wheel 恰三份 Skill，逐字节等于来源文件；提取 wheel 后从包路径构建 SkillSnapshot 成功 |
| V2-D2 | PASS | `pytest -q tests/test_deep_diagnosis_skills.py` 9 PASS；首个模型请求含三个名称/描述但无正文，三场景实际读取对应 Skill，问候零读取；使用原生扫描和 read_file |
| V2-D3 | PASS | 同组 FakeModel/Mock：恰六工具、路径白名单、并行 read 第3次/Reader 第7次拒绝；403/404/timeout 有 error 回执与未核验结论，预算随正常新轮重置 |
| V2-D4 | PASS | 独立实际 Aegra/Mock/PostgreSQL；`ISSUE75_TEST_API_URL=http://127.0.0.1:12075 .venv/bin/pytest -q tests/test_skills_protocol.py` 1 PASS；四场景 SSE end、完整调用/回执配对及下一轮历史；输入使用 Web content blocks |
| V2-D5 | PASS | AO Browser 自动化实测：三诊断均可见 read_file、四 Reader、中文 UNKNOWN/UID；重开 CrashLoop 完成 Thread 保留工具历史/结论，正常新 Human 问候成功；新 Thread 问候无工具。真人测试 NOT RUN |
| V2-D6 | PASS | 全量 `.venv/bin/pytest -q`：867 PASS / 9 SKIP / 4 Sandbox loopback FAIL（163.55s）；在 Host 单独重跑四项均 PASS（3.70s）。后续 FakeModel content-block 修正再跑9项契约 PASS及HTTP 1 PASS。旧 pin 中途恢复 OUT OF SCOPE / NOT RUN |
| V2-D7 | PASS | 下表8例OFF/ON，命中与错误选取有确定性断言；只评价协议。真实模型质量、Provider Token/成本 NOT RUN |
| V2-D8 | NOT RUN | Ruff、diff 检查、Web lint/build 本地 PASS；独立 Skills CI job 已加入。远端 CI 与 PR Review 尚待当前提交执行，结果见 PR checks / review，不预填 PASS |

全量中的 9 SKIP 为 8 项需要独立 #78 持久化服务的既有测试，以及没有显式 URL 时跳过的 Skills HTTP 测试；后者另以实际服务运行通过。#78 服务未复用或修改，CI 保留其独立 persistence job。本地不把 SKIP 当 PASS。

Web lint 为 0 errors / 18 个既有 warnings。标准 `pnpm build` 在继承运行环境下先因字体网络、内部 CSS worker 端口失败；使用启动器同样的最小环境在 Host 跑 `pnpm build` 后成功（含 TypeScript），保留既有 Tailwind module warning。没有升级依赖或变更公共构建配置。

## 小评测（确定性协议，非真实模型效果）

命令：`TRIAGE_ENV=test LANGSMITH_TRACING=false OTEL_SDK_DISABLED=true server/.venv/bin/python server/tests/test_deep_diagnosis_skills.py off-on`。延迟是进程内图执行时间，不含构图、Provider 或 HTTP；字符数为累计模型请求的序列化字符代理量，**不是 Token**。

| 合成案例 | ON Skill / 错误选择 | 工具数 OFF→ON | 延迟秒 OFF→ON | 请求字符 OFF→ON |
| --- | --- | --- | --- | --- |
| CrashLoopBackOff | crashloop / 0 | 4→5 | .0231→.0304 | 17860→36969 |
| OOMKilled | oom / 0 | 4→5 | .0200→.0320 | 17800→36937 |
| ImagePullBackOff | imagepull / 0 | 4→5 | .0196→.0289 | 17628→37022 |
| 你好 | 无 / 0 | 0→0 | .0044→.0064 | 1615→2905 |
| healthy | 无 / 0 | 4→4 | .0206→.0256 | 17580→24320 |
| 疑似 OOM，证据不足 | oom / 0 | 4→5 | .0191→.0292 | 17810→36949 |
| ErrImagePull | imagepull / 0 | 4→5 | .0190→.0285 | 17608→36998 |
| 频繁重启 | crashloop / 0 | 4→5 | .0191→.0297 | 17800→36897 |

六个需技能案例命中6/6；两个不需技能案例读取0；错误选择0。诊断报告引用本轮 `skills-pods_get`、`skills-events_list`、`skills-pods_log` 与实际合成 UID。FakeModel 固定协议不能证明真实模型会正确选取、理解正文或提高诊断质量。无指标/历史峰值时仍 UNKNOWN；问候无需强制 Todo。新增测试曾定位 Web content-block 兼容问题，修正后在 HTTP 与浏览器重验。

## 可重复验证

```sh
cd server
uv run --frozen ruff check src tests ../scripts/skills_demo.py
uv run --frozen pytest -q
# 另一个终端运行 make dev-deep-skills-demo 后：
ISSUE75_TEST_API_URL=http://127.0.0.1:12075 uv run --frozen pytest -q tests/test_skills_protocol.py
cd ../apps/web
pnpm lint
pnpm build
cd ../..
git diff --check
```

CI 的 `skills` job 单独启动 PostgreSQL、FakeModel Aegra 与 Mock MCP，并执行离线契约及 HTTP/SSE 测试；正式 python/web/persistence/compose jobs 保留。不合并、不关闭 #75，交付供审查。
