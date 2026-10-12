#!/usr/bin/env python3
"""Exercise the local Agent Protocol without any LLM or Kubernetes dependency."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = os.environ.get("ACCEPTANCE_ENV_FILE", ".env")


def compose_command(*arguments):
    project = os.environ.get("ACCEPTANCE_COMPOSE_PROJECT")
    if project:
        return ["docker", "compose", "-p", project, "--env-file", ENV_FILE,
                "-f", "infra/compose.yaml", *arguments]
    return ["./scripts/compose.sh", *arguments]


def local_port():
    try:
        for line in Path(ENV_FILE).read_text(encoding="utf-8").splitlines():
            if line.startswith("API_PORT="):
                return int(line.split("=", 1)[1].strip())
    except OSError:
        pass
    return 12026


def local_token():
    for line in Path(ENV_FILE).read_text(encoding="utf-8").splitlines():
        if line.startswith("DEMO_API_TOKEN="):
            token = line.split("=", 1)[1].strip()
            if token and token != "REPLACE_WITH_RANDOM_URL_SAFE_TOKEN":
                return token
    raise RuntimeError("DEMO_API_TOKEN is missing")


BASE = os.environ.get("API_BASE", f"http://127.0.0.1:{local_port()}").rstrip("/")
TOKEN = local_token()
results = []


def record(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")


def request(path, method="GET", body=None, token=TOKEN):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={**({"Content-Type": "application/json"} if data else {}),
                 **({"X-Api-Key": token} if token else {})},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def stream(thread_id, body, token=TOKEN):
    req = urllib.request.Request(
        BASE + f"/threads/{thread_id}/runs/stream",
        data=json.dumps({"assistant_id": "agent", "stream_mode": ["updates", "values", "messages-tuple"], **body}).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                 **({"X-Api-Key": token} if token else {})},
        method="POST",
    )
    events = []
    with urllib.request.urlopen(req, timeout=90) as response:
        event_type = ""
        data_lines = []
        for raw in response:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif not line and data_lines:
                events.append((event_type, "\n".join(data_lines)))
                event_type, data_lines = "", []
        if data_lines:
            events.append((event_type, "\n".join(data_lines)))
    return events


def state(thread_id):
    return request(f"/threads/{thread_id}/state")


def messages_text(snapshot):
    return json.dumps(snapshot.get("values", {}).get("messages", []), ensure_ascii=False)


def wait_health():
    for _ in range(60):
        try:
            if request("/health").get("status") == "healthy":
                return True
        except (OSError, ValueError):
            pass
        time.sleep(2)
    return False


def denied(fn):
    try:
        fn()
    except urllib.error.HTTPError as exc:
        return exc.code == 401
    return False


def audit_ok():
    logs = subprocess.run(
        compose_command("logs", "api", "--no-color", "--tail=2000"),
        capture_output=True, text=True, check=True,
    ).stdout
    events = [line for line in logs.splitlines() if '"event": "mcp_tool_call"' in line]
    return (TOKEN not in logs and
            any('"outcome": "success"' in line for line in events) and
            any('"outcome": "rejected"' in line for line in events))


try:
    record("health", wait_health())
    assistants = request("/assistants/search", "POST", {"limit": 100})
    record("graph agent", any(a.get("graph_id") == "agent" for a in assistants))
    thread = request("/threads", "POST", {})
    thread_id = thread["thread_id"]
    record("thread create", bool(thread_id))
    record("anonymous assistant/thread/state/history/run/SSE denied", all([
        denied(lambda: request("/assistants/search", "POST", {"limit": 1}, token=None)),
        denied(lambda: request(f"/threads/{thread_id}", token=None)),
        denied(lambda: request(f"/threads/{thread_id}/state", token=None)),
        denied(lambda: request(f"/threads/{thread_id}/history", token=None)),
        denied(lambda: request(f"/threads/{thread_id}/runs", "POST", {"assistant_id": "agent"}, token=None)),
        denied(lambda: stream(thread_id, {"input": {"messages": []}}, token=None)),
    ]))
    record("wrong key thread/run denied", all([
        denied(lambda: request(f"/threads/{thread_id}", token="wrong-key")),
        denied(lambda: stream(thread_id, {"input": {"messages": []}}, token="wrong-key")),
    ]))

    first = stream(thread_id, {"input": {"messages": [{"role": "human", "content": "hello"}]}})
    record("run and stream", bool(first) and "Phase 1B echo" in messages_text(state(thread_id)))
    second = stream(thread_id, {"input": {"messages": [{"role": "human", "content": [{"type": "text", "text": "pods kube-triage-demo"}]}]}})
    second_text = json.dumps(second, ensure_ascii=False) + messages_text(state(thread_id))
    record("MCP adapter tool call/result", "pods_list_in_namespace" in second_text and
           "static-fixture" in second_text and "crashloop-pod" in second_text)
    stream(thread_id, {"input": {"messages": [{"role": "human", "content":
        "pod kube-triage-demo crashloop-pod"}]}})
    record("container waiting reason", "CrashLoopBackOff" in messages_text(state(thread_id)))
    stream(thread_id, {"input": {"messages": [{"role": "human", "content": "pod kube-triage-demo healthy-pod"}]}})
    record("pod mock", "healthy-pod" in messages_text(state(thread_id)))
    stream(thread_id, {"input": {"messages": [{"role": "human", "content": "events kube-triage-demo"}]}})
    record("events mock", "Back-off restarting failed container" in messages_text(state(thread_id)))
    stream(thread_id, {"input": {"messages": [{"role": "human", "content": "logs kube-triage-demo crashloop-pod"}]}})
    record("logs mock", "database unavailable" in messages_text(state(thread_id)))
    for namespace in ("default", "kube-system"):
        stream(thread_id, {"input": {"messages": [{"role": "human", "content": f"pods {namespace}"}]}})
        record(f"namespace {namespace} denied", "Namespace denied" in messages_text(state(thread_id)))
    record("audit success/rejection without token", audit_ok())
    record("multi-round history", len(request(f"/threads/{thread_id}/history")) >= 3)

    interrupted = stream(thread_id, {"input": {"messages": [{"role": "human", "content": [{"type": "text", "text": "/approve-demo"}]}]}})
    before = state(thread_id)
    interrupted_text = json.dumps(interrupted, ensure_ascii=False) + json.dumps(before, ensure_ascii=False)
    record("interrupt pending", "demo_approval" in interrupted_text and bool(before.get("next")))
    record("anonymous/wrong-key resume denied", all([
        denied(lambda: stream(thread_id, {"command": {"resume": {"decision": "approve"}}}, token=None)),
        denied(lambda: stream(thread_id, {"command": {"resume": {"decision": "approve"}}}, token="wrong-key")),
    ]))
    stream(thread_id, {"command": {"resume": {"decision": "approve"}}})
    record("resume approved", "approval approved" in messages_text(state(thread_id)))

    stream(thread_id, {"input": {"messages": [{"role": "human", "content": "/approve-demo"}]}})
    stream(thread_id, {"command": {"resume": {"decision": "reject"}}})
    record("resume rejected", "approval rejected" in messages_text(state(thread_id)))

    subprocess.run(compose_command("restart", "api"), check=True)
    record("api restart health", wait_health())
    after = state(thread_id)
    record("thread persists after api restart", "approval rejected" in messages_text(after))
    record("history persists after api restart", len(request(f"/threads/{thread_id}/history")) >= 6)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
    record("acceptance continuation", False, str(exc))

sys.exit(0 if results and all(ok for _, ok in results) else 1)
