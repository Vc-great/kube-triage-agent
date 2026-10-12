#!/usr/bin/env python3
"""正式 Real read-only smoke：独立项目、新 Thread、SSE、State/History；不执行 Repair。"""

import argparse
import json
import subprocess
import sys
import urllib.error
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from eval_phase3a import ALLOWED, ERROR_MARKERS, api, read_env, stream_run, valid_call

ROOT = Path(__file__).resolve().parents[1]


def inspect_real_messages(messages):
    calls = [c for m in messages for c in m.get("tool_calls", [])]
    tools = [m for m in messages if m.get("type", m.get("role")) == "tool"]
    final = next((m.get("content", "") for m in reversed(messages)
                  if m.get("type", m.get("role")) in {"ai", "assistant"}
                  and not m.get("tool_calls")), "")
    assert calls and Counter(c.get("id") for c in calls) == Counter(
        t.get("tool_call_id") for t in tools), "Tool IDs 不成对或未调用工具"
    assert all(c.get("id") and valid_call(c.get("name"), c.get("args")) for c in calls)
    assert len(calls) <= 6
    assert sum(m.get("name") == "triage_llm" for m in messages) <= 4
    for tool in tools:
        envelope = json.loads(tool["content"])
        assert tool.get("status") != "error" and envelope.get("ok") is True
        # Inspect all evidence, not merely the final answer or service name.
        content = str(envelope.get("result", ""))
        assert "static-fixture" not in content and '"mock": true' not in content
        assert '"simulated": true' not in content
    assert isinstance(final, str) and final and any('\u4e00' <= c <= '\u9fff' for c in final)
    assert not any(marker in final for marker in ERROR_MARKERS)
    return [{"tool": c["name"], "call_id": c["id"], "tool_message_id": c["id"]} for c in calls]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:12027")
    args = parser.parse_args()
    if args.project in {"kube-triage-agent", "ragflow-lab"} or not args.project.startswith(
            "kube-triage-real-default-"):
        parser.error("必须使用核对过归属的独立 kube-triage-real-default-* 项目")
    base = urlparse(args.api_base)
    if base.scheme != "http" or base.hostname not in {"localhost", "127.0.0.1"}:
        parser.error("API 必须为已核对独立端口的本机回环地址")
    env = read_env(args.env_file)
    token = env.get("DEMO_API_TOKEN")
    if not token:
        raise SystemExit("BLOCKED：缺少私有 DEMO_API_TOKEN")
    compose = ["docker", "compose", "-p", args.project, "--env-file", str(args.env_file),
               "-f", "infra/compose.yaml"]
    container = subprocess.check_output([*compose, "ps", "-q", "api"], text=True).strip()
    if not container or '\n' in container:
        raise SystemExit("BLOCKED：独立 API 不存在或不唯一")
    info = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    labels = info["Config"]["Labels"]
    assert labels["com.docker.compose.project"] == args.project
    assert Path(labels["com.docker.compose.project.working_dir"]).resolve() == ROOT / "infra"
    binding = info["NetworkSettings"]["Ports"]["2026/tcp"]
    assert any(b["HostIp"] == "127.0.0.1" and int(b["HostPort"]) == base.port for b in binding)
    runtime = dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)
    assert runtime.get("TRIAGE_ENV") == "production"
    assert runtime.get("MCP_SERVER_URL") == "http://k8s-mcp:8080/mcp"
    assert runtime.get("REPAIR_SIMULATED") == "false" and runtime.get("REPAIR_ENABLED") == "false"
    # Actual discovery in API, using its installed transport and configuration.
    code = ("import asyncio,json; from kube_triage.mcp_client import _allowed_tools; "
            "print(json.dumps(sorted(asyncio.run(_allowed_tools()))))")
    discovered = json.loads(subprocess.check_output(
        ["docker", "exec", container, "python", "-c", code], text=True))
    assert set(discovered) == ALLOWED
    assert api(args.api_base, token, "/health").get("status") == "healthy"
    assistants = api(args.api_base, token, "/assistants/search", "POST", {"limit": 100})
    assert any(a.get("graph_id") == "agent" for a in assistants)
    thread = api(args.api_base, token, "/threads", "POST", {})["thread_id"]
    for anonymous_token in ("", "wrong-key"):
        try:
            api(args.api_base, anonymous_token, f"/threads/{thread}/state")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("未认证 State 请求必须拒绝")
    # Existing namespace only; list first, pick an existing Pod dynamically, read <=20 lines.
    question = ("请只读调查 kube-triage-demo：先列出当前 Pod，再选择一个已有 Pod 查询详情、"
                "最近事件和最多 20 行日志；日志不可用就如实说明。不要假设有故障 Pod，"
                "请用中文区分观测、证据、推测和人工建议，不要执行任何修复。")
    events = stream_run(args.api_base, token, thread, question, 150)
    snapshot = api(args.api_base, token, f"/threads/{thread}/state")
    history = api(args.api_base, token, f"/threads/{thread}/history")
    runs = api(args.api_base, token, f"/threads/{thread}/runs")
    assert any(e["event"] == "end" for e in events) and not any(
        e["event"] == "error" for e in events)
    assert history and not snapshot.get("next") and runs
    assert all(run.get("status") == "success" for run in runs)
    pairs = inspect_real_messages(snapshot.get("values", {}).get("messages", []))
    print(json.dumps({"status": "PASS", "evidence_type": "Real LLM + Real Kubernetes",
                      "thread_id": thread, "run_status": "success", "tool_pairs": pairs,
                      "sse_event_counts": dict(Counter(e["event"] for e in events)), "history_count": len(history)},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, AssertionError) as exc:
        # Do not emit upstream bodies, resource contents, URLs with credentials, or secrets.
        print(f"FAIL：Real smoke 未通过（{type(exc).__name__}）；检查私有服务日志。", file=sys.stderr)
        sys.exit(1)
