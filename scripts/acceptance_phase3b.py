#!/usr/bin/env python3
"""Aegra/Mock-only acceptance. Requires an isolated Compose project, never a cluster."""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".local" / "phase3b.env"


def setting(name):
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1]
    raise RuntimeError(f"Missing {name}")


BASE = os.environ.get("API_BASE", "http://127.0.0.1:12027").rstrip("/")
TOKEN = setting("DEMO_API_TOKEN")
results = []


def record(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")


def request(path, method="GET", body=None, token=TOKEN):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["X-Api-Key"] = token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def stream(thread, payload, token=TOKEN):
    data = json.dumps({"assistant_id": "agent", "stream_mode": ["updates", "values"],
                       **payload}).encode()
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["X-Api-Key"] = token
    req = urllib.request.Request(BASE + f"/threads/{thread}/runs/stream", data=data,
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read().decode("utf-8")


def new_thread():
    return request("/threads", "POST", {})["thread_id"]


def start(thread):
    return stream(thread, {"input": {"messages": [{"role": "human", "content": "/repair-demo"}]}})


def snapshot(thread):
    return request(f"/threads/{thread}/state")


def denied(thread, payload, token):
    try:
        stream(thread, payload, token=token)
    except urllib.error.HTTPError as exc:
        return exc.code == 401
    return False


def proposal(thread):
    state = snapshot(thread)
    return state["values"].get("repair_proposal"), state


try:
    for _ in range(60):
        try:
            if request("/health").get("status") == "healthy":
                break
        except (OSError, ValueError):
            time.sleep(2)
    else:
        raise RuntimeError("API health timeout")
    record("A03 health and authenticated Aegra thread", True)

    legacy_thread = new_thread()
    stream(legacy_thread, {"input": {"messages": [{"role": "human", "content": "status"}]}})
    record("A02 legacy echo", "Phase 1B" in json.dumps(snapshot(legacy_thread)["values"],
                                                       ensure_ascii=False) or
           "试试 pods" in json.dumps(snapshot(legacy_thread)["values"], ensure_ascii=False))
    stream(legacy_thread, {"input": {"messages": [{"role": "human",
        "content": "pods kube-triage-demo"}]}})
    record("A02 four-tool Reader path", "pods_list_in_namespace" in
           json.dumps(snapshot(legacy_thread)["values"], ensure_ascii=False))
    stream(legacy_thread, {"input": {"messages": [{"role": "human",
        "content": "/approve-demo"}]}})
    record("A02 legacy mock interrupt", bool(snapshot(legacy_thread).get("next")))
    stream(legacy_thread, {"command": {"resume": {"decision": "reject"}}})
    record("A02 legacy mock resume", "approval rejected" in
           json.dumps(snapshot(legacy_thread)["values"], ensure_ascii=False))

    reject_thread = new_thread()
    reject_sse = start(reject_thread)
    reject_proposal, reject_state = proposal(reject_thread)
    record("A03 checkpointed interrupt and SSE", bool(reject_state.get("next")) and
           reject_proposal.get("simulated") is True and
           reject_proposal["proposal_id"] in reject_sse)
    record("A06 unauthenticated resume denied", denied(reject_thread,
        {"command": {"resume": {"decision": "approve",
                                "proposal_id": reject_proposal["proposal_id"]}}}, None))
    stream(reject_thread, {"command": {"resume": {"decision": "reject",
        "proposal_id": reject_proposal["proposal_id"]}}})
    record("A04 reject", snapshot(reject_thread)["values"]["repair_status"] == "rejected")

    wrong_thread = new_thread()
    start(wrong_thread)
    wrong_proposal, _ = proposal(wrong_thread)
    stream(wrong_thread, {"command": {"resume": {"decision": "approve",
        "proposal_id": reject_proposal["proposal_id"]}}})
    record("A06 cross-thread proposal rejected",
           snapshot(wrong_thread)["values"]["repair_status"] == "rejected")

    approve_thread = new_thread()
    start(approve_thread)
    approve_proposal, _ = proposal(approve_thread)
    record("A03 stable proposal ID", approve_proposal["proposal_id"] ==
           snapshot(approve_thread)["values"]["repair_proposal"]["proposal_id"])
    stream(approve_thread, {"command": {"resume": {"decision": "approve",
        "proposal_id": approve_proposal["proposal_id"]}}})
    done = snapshot(approve_thread)["values"]
    result = done.get("repair_result") or {}
    record("A05 simulated fixed scale and verification",
           done.get("repair_status") == "finished" and result.get("simulated") is True and
           result.get("observed_replicas") == 1 and result.get("write_attempted") is True)
    record("A09 history includes approval", len(request(f"/threads/{approve_thread}/history")) >= 3)
    print("Thread summaries: reject, cross-thread, approve created; IDs omitted from stdout.")
except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
    record("acceptance continuation", False, type(exc).__name__)

sys.exit(0 if results and all(results) else 1)
