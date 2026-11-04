"""Render private learning artifacts from evidence; no model or network access."""

import html
import json
import os
from pathlib import Path

TITLES = {"S01": "正常查询", "S05": "权限拒绝", "S06": "外层成功、业务失败"}


def write_text(path, content):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600),
                   "w") as stream:
        stream.write(content)


def usage(row):
    """Provider-reported Usage only; absence remains unknown."""
    evidence = row.get("evidence_path")
    if not evidence or not (Path(evidence) / "private.json").is_file():
        return None
    raw = json.loads((Path(evidence) / "private.json").read_text())
    messages = (raw.get("state") or {}).get("values", {}).get("messages", [])
    generations = [m for m in messages if m.get("type", m.get("role")) in {"ai", "assistant"}
                   and (m.get("response_metadata") or {}).get("model_name")]
    details = [m.get("usage_metadata") for m in generations]
    if not details or any(not isinstance(d, dict) or any(
            not isinstance(d.get(k), int) for k in ("input_tokens", "output_tokens", "total_tokens"))
                          for d in details):
        return None
    return {k: sum(d[k] for d in details) for k in ("input_tokens", "output_tokens", "total_tokens")}


def render_report(output, report):
    lines = ["# Langfuse 面试案例一：工具失败后的执行与回答", "",
             f"活动：{report['activity_id']}；已预占 {report['reserved_runs']}/6 Run。", "",
             "真实模型＋合成 Mock；回答审阅来源为 agent_review，不是真人独立评审。", "",
             "执行完成、工具成功、回答合理分别判断；未知不补零。费用实账单 UNKNOWN。", "",
             "| 场景 | 执行状态 | 工具业务结果 | 原生完整性 | 回答审阅 | Trace |",
             "| --- | --- | --- | --- | --- | --- |"]
    blocks = []
    for row in report["runs"]:
        cloud = row.get("cloud") or {}
        review = row.get("diagnosis_review") or {}
        records = (row.get("fault_evidence") or {}).get("records", [])
        outcomes = ", ".join(sorted({r["outcome"] for r in records})) or "UNKNOWN"
        url = cloud.get("url") if cloud.get("trace_verified") else None
        link = f"[打开]({url})" if url else "PENDING / NOT RUN"
        key = row["key"]
        lines.append(f"| {key} {TITLES[row['scenario_id']]} | {row['protocol_status']} | "
                     f"{outcomes} | {cloud.get('native_trace_complete', 'UNKNOWN')} | "
                     f"{review.get('status', 'UNKNOWN')} | {link} |")
        data = {"execution": row["protocol_status"], "sse_error": row.get("sse_error"),
                "scenario_id": row["scenario_id"],
                "fixture_version": ("issue12-blind-v1-phase-a2" if row["scenario_id"] == "S01"
                                    else "issue12-blind-v1-phase-b1"),
                "fixture_version_source": "obs_lab.execute request metadata",
                "start": row.get("start"), "end": row.get("end"),
                "models_observed": row.get("models_observed", []),
                "model_decisions": row.get("model_decisions"), "tool_count": row.get("tool_count"),
                "model_requests": row.get("model_requests"),
                "tool_outcomes": records, "tool_call_proof": cloud.get("tool_call_proof", []),
                "business_proof": cloud.get("business_proof", []),
                "trace_id": cloud.get("trace_id"),
                "case1_trace_ready": row.get("case1_trace_ready", False),
                "case1_fault_event": row.get("case1_fault_event"),
                "original_ingestion_state": row.get("ingestion_state"),
                "execution_error": row.get("execution_error"),
                "original_ingestion_error": row.get("ingestion_error"),
                "report_read_error": row.get("report_read_error"),
                "scenario_observable": cloud.get("scenario_observable", "UNKNOWN"),
                "scenario_missing": cloud.get("scenario_missing", []),
                "native_missing": cloud.get("native_missing", []),
                "run_id": row.get("run_id"), "thread_id": row.get("thread_id"),
                "usage": usage(row), "usage_source": "State AIMessage.usage_metadata; null means unknown",
                "actual_billed_cost": "UNKNOWN", "cost_source": "No Provider billing statement collected",
                "review": review, "evidence_path": row.get("evidence_path"),
                "final_answer": row.get("final_answer", "未取得回答")}
        details = json.dumps(data, ensure_ascii=False, indent=2)
        blocks.append((key, url, details, data))
    lines += ["", "## 查看顺序", "",
              "1. S01 的 Tree：找到模型→工具→模型，点击 Generation 查看输入输出。",
              "2. S05：点击 pods_get，再看右侧 Preview 的 Error；之后选择最后一个 ChatOpenAI。",
              "3. S06：对比 pods_log 原生状态和 reader_outcome 的业务结果，核对内层 ok=false。",
              "4. 对比最终回答和实际证据：没有拿到日志时，是否仍编造日志内容或确定根因？",
              "5. Timeline 只比较关键路径；父子节点耗时不能简单相加。",
              "6. 缺失输入输出时查看私有 State/History，缺失 TTFT 或费用不推算。",
              "", "以下数据仅限本机学习；不要将完整回答或原始轨迹提交到公共仓库。", ""]
    for key, url, details, _ in blocks:
        lines += [f"## {key}", "", f"Trace：{url or '尚未确认'}", "", "~~~json", details, "~~~", ""]
    write_text(output / "index.md", "\n".join(lines))
    cards = []
    for key, url, details, data in blocks:
        anchor = (f'<a href="{html.escape(url, quote=True)}">打开本地 Trace</a>'
                  if url else "Trace 尚未确认或尚未运行")
        summary = (f"执行：{data['execution']} · 回答审阅：{data['review'].get('status', 'UNKNOWN')}"
                   f" · 模型决策：{data['model_decisions']} · 工具调用：{data['tool_count']}")
        outcomes = ", ".join(f"{r['name']}: {r['outcome']}" for r in data["tool_outcomes"]) or "UNKNOWN"
        cards.append(f"<section><h2>{html.escape(key)} · {html.escape(TITLES[key[:3]])}</h2>"
                     f"{anchor}<p>{html.escape(summary)}</p><p>{html.escape(outcomes)}</p>"
                     f"<h3>最终回答</h3><pre>{html.escape(data['final_answer'])}</pre>"
                     f"<h3>审阅依据</h3><p>{html.escape(data['review'].get('reason', '尚未审阅'))}</p>"
                     f"<details><summary>证据索引、关联 ID 与用量</summary>"
                     f"<pre>{html.escape(details)}</pre></details></section>")
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Langfuse 面试案例一</title>'
            '<style>body{font:16px/1.6 system-ui;max-width:1050px;margin:40px auto;padding:0 20px;'
            'background:#f5f7fa;color:#17253a}section{background:white;padding:24px;margin:20px 0;'
            'border:1px solid #dce3ed;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;'
            'font:14px/1.65 monospace}a{color:#1458b8}h1{font-size:28px}</style>'
            f'<h1>工具失败后 Agent 继续运行</h1><p>活动 {html.escape(report["activity_id"])} · '
            f'{report["reserved_runs"]}/6 Run</p>'
            '<p>按执行状态 → 工具业务结果 → 回答依据阅读。agent_review 不是独立人工评审。</p>'
            '<p>先看 S01，再看 S05 和 S06。进入 Trace 后依次使用 Tree、右侧 Preview、Timeline。'
            'Token 仅来自实际 Usage，费用实账单未知。</p>' + "".join(cards) + "</html>")
    write_text(output / "index.html", page)
