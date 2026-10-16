#!/usr/bin/env python3
"""dev01/原生开发真实只读验收；不输出资源日志或凭据，不执行 Repair。"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from acceptance import inspect_real_messages
from eval_phase3a import ALLOWED, api, read_env, stream_run, write_private

ROOT = Path(__file__).resolve().parents[1]


def check_cors(base):
    for origin in ("http://192.168.31.110:13000", "http://localhost:13000",
                   "http://127.0.0.1:13000"):
        request = urllib.request.Request(base + "/threads", method="OPTIONS", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key,content-type"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.headers.get("Access-Control-Allow-Origin") == origin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("production", "development"), required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    env = read_env(args.env_file)
    token = env.get("DEMO_API_TOKEN")
    assert token, "缺少 API Token"
    if args.target == "production":
        assert ROOT == Path("/www/app/kube-triage-agent")
        assert subprocess.check_output(["hostname"], text=True).strip() == "dev01"
        base = "http://192.168.31.110:12026"
        container = subprocess.check_output([str(ROOT / "scripts/dev01-compose.sh"),
                                             "ps", "-q", "api"], text=True).strip()
        assert container and "\n" not in container
        info = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
        labels = info["Config"]["Labels"]
        assert labels["com.docker.compose.project"] == "kube-triage-agent"
        assert Path(labels["com.docker.compose.project.working_dir"]) == ROOT / "infra"
        assert info["NetworkSettings"]["Ports"]["2026/tcp"] == [
            {"HostIp": "192.168.31.110", "HostPort": "12026"}]
        runtime = dict(v.split("=", 1) for v in info["Config"]["Env"] if "=" in v)
        assert runtime["TRIAGE_ENV"] == "production"
        assert runtime["MCP_SERVER_URL"] == "http://k8s-mcp:8080/mcp"
        assert runtime["POSTGRES_DB"] == "kube_triage_agent"
        assert runtime["REDIS_URL"] == "redis://redis:6379/0"
        assert runtime["REPAIR_ENABLED"] == runtime["REPAIR_SIMULATED"] == "false"
        code = ("import asyncio,json; from kube_triage.mcp_client import _allowed_tools; "
                "print(json.dumps(sorted(asyncio.run(_allowed_tools()))))")
        discovered = json.loads(subprocess.check_output(
            ["docker", "exec", container, "python", "-c", code], text=True,
            stderr=subprocess.DEVNULL))
    else:
        state = json.loads((ROOT / ".local/dev/state.json").read_text())
        assert state["mode"] == "real" and state["status"] == "ready"
        base = "http://127.0.0.1:12026"
        os.environ.update(TRIAGE_ENV="development", REPAIR_SIMULATED="false",
                          MCP_SERVER_URL="http://127.0.0.1:18080/mcp")
        sys.path.insert(0, str(ROOT / "server/src"))
        from kube_triage.mcp_client import _allowed_tools
        discovered = list(asyncio.run(_allowed_tools()))
    assert set(discovered) == ALLOWED
    assert api(base, token, "/health")["status"] == "healthy"
    check_cors(base)
    thread = api(base, token, "/threads", "POST", {})["thread_id"]
    for invalid in ("", "wrong-key"):
        try:
            api(base, invalid, f"/threads/{thread}/state")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("API 必须拒绝未认证请求")
    question = ("请只读调查 kube-triage-demo：先列出当前 Pod，若列表中存在 triage-sample，"
                "选择它；否则选择一个 Running 且 Ready 的已有 Pod。查询该 Pod 详情、"
                "最近事件和最多 20 行日志。events_list 只传 namespace，"
                "不要添加 fieldSelector 或其他过滤参数；日志不可用就如实说明。不要假设有故障 Pod，"
                "请用中文区分观测、证据、推测和人工建议，不要执行任何修复。")
    events = stream_run(base, token, thread, question, 180)
    snapshot = api(base, token, f"/threads/{thread}/state")
    history = api(base, token, f"/threads/{thread}/history")
    runs = api(base, token, f"/threads/{thread}/runs")
    assert any(e["event"] == "end" for e in events)
    assert not any(e["event"] == "error" for e in events)
    assert history and not snapshot.get("next") and runs
    assert all(run["status"] == "success" for run in runs)
    pairs = inspect_real_messages(snapshot["values"]["messages"])
    result = {"status": "PASS", "target": args.target, "thread_id": thread,
              "run_status": "success", "tool_pairs": pairs,
              "sse_event_counts": dict(Counter(e["event"] for e in events)),
              "history_count": len(history)}
    (ROOT / ".local").mkdir(mode=0o700, exist_ok=True)
    write_private(ROOT / f".local/{args.target}-smoke.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, AssertionError,
            subprocess.SubprocessError) as error:
        print(f"FAIL：真实验收未通过（{type(error).__name__}）；检查私有日志。", file=sys.stderr)
        sys.exit(1)
