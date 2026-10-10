#!/usr/bin/env python3
"""Exercise the local Agent Protocol without any LLM or Kubernetes dependency."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


def local_port():
    try:
        for line in open(".env", encoding="utf-8"):
            if line.startswith("API_PORT="):
                return int(line.split("=", 1)[1].strip())
    except OSError:
        pass
    return 12026


BASE = os.environ.get("API_BASE", f"http://127.0.0.1:{local_port()}").rstrip("/")
results = []


def record(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")


def request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def stream(thread_id, body):
    req = urllib.request.Request(
        BASE + f"/threads/{thread_id}/runs/stream",
        data=json.dumps({"assistant_id": "agent", "stream_mode": ["updates", "values", "messages-tuple"], **body}).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
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


try:
    record("health", wait_health())
    assistants = request("/assistants/search", "POST", {"limit": 100})
    record("graph agent", any(a.get("graph_id") == "agent" for a in assistants))
    thread = request("/threads", "POST", {})
    thread_id = thread["thread_id"]
    record("thread create", bool(thread_id))

    first = stream(thread_id, {"input": {"messages": [{"role": "human", "content": "hello"}]}})
    record("run and stream", bool(first) and "Phase 0 mock echo" in messages_text(state(thread_id)))
    second = stream(thread_id, {"input": {"messages": [{"role": "human", "content": [{"type": "text", "text": "status"}]}]}})
    second_text = json.dumps(second, ensure_ascii=False) + messages_text(state(thread_id))
    record("mock tool call/result", "get_demo_cluster_status" in second_text and "mock" in second_text)
    record("two-round history", len(request(f"/threads/{thread_id}/history")) >= 3)

    interrupted = stream(thread_id, {"input": {"messages": [{"role": "human", "content": [{"type": "text", "text": "/approve-demo"}]}]}})
    before = state(thread_id)
    interrupted_text = json.dumps(interrupted, ensure_ascii=False) + json.dumps(before, ensure_ascii=False)
    record("interrupt pending", "demo_approval" in interrupted_text and bool(before.get("next")))
    stream(thread_id, {"command": {"resume": {"decision": "approve"}}})
    record("resume approved", "approval approved" in messages_text(state(thread_id)))

    stream(thread_id, {"input": {"messages": [{"role": "human", "content": "/approve-demo"}]}})
    stream(thread_id, {"command": {"resume": {"decision": "reject"}}})
    record("resume rejected", "approval rejected" in messages_text(state(thread_id)))

    subprocess.run(["./scripts/compose.sh", "restart", "api"], check=True)
    record("api restart health", wait_health())
    after = state(thread_id)
    record("thread persists after api restart", "approval rejected" in messages_text(after))
    record("history persists after api restart", len(request(f"/threads/{thread_id}/history")) >= 6)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
    record("acceptance continuation", False, str(exc))

sys.exit(0 if results and all(ok for _, ok in results) else 1)
