"""Real Aegra/PG/FakeModel/Mock MCP protocol checks (explicit local opt-in)."""

import json
import os
import time
from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def api():
    url = os.getenv("ISSUE78_TEST_API_URL")
    if not url:
        pytest.skip("requires local issue78 FakeModel Aegra profile")
    if url not in {"http://127.0.0.1:12079", "http://localhost:12079"}:
        pytest.fail("Issue #78 protocol tests require the dedicated local endpoint")
    with httpx.Client(base_url=url, headers={"x-api-key": os.environ["DEMO_API_TOKEN"]},
                      timeout=30) as client:
        yield client


def create(api):
    response = api.post("/threads", json={})
    response.raise_for_status()
    return response.json()["thread_id"]


def sync(api, thread):
    response = api.post("/app/history/sync", json={"thread_id": thread})
    response.raise_for_status()
    return response.json()


def history(api, thread):
    response = api.get(f"/app/history/threads/{thread}/messages")
    response.raise_for_status()
    return response.json()


def test_real_protocol_two_rounds_sse_history_evidence_and_reentry(api):
    thread = create(api)
    for turn in range(2):
        request = {"assistant_id": "agent", "input": {"messages": [
            {"type": "human", "id": str(uuid4()), "content": "重复的合成问题"}]},
            "stream_mode": ["messages", "updates", "custom"]}
        with api.stream("POST", f"/threads/{thread}/runs/stream", json=request) as response:
            response.raise_for_status()
            body = "".join(response.iter_text())
            assert "event: messages" in body and "event: updates" in body
        # SSE end and final thread status commit can be separated briefly.
        for _ in range(20):
            status = api.get(f"/threads/{thread}").json()["status"]
            if status != "busy":
                break
            time.sleep(.1)
        assert sync(api, thread)["added"] == 2
        assert sync(api, thread)["added"] == 0
        saved = history(api, thread)
        assert len(saved["messages"]) == (turn + 1) * 2
        assert all(m["status"] == "completed" for m in saved["messages"])
    state = api.get(f"/threads/{thread}/state").json()
    tools = [json.loads(m["content"]) for m in state["values"]["messages"] if m["type"] == "tool"]
    assert len(tools) == 2
    run_ids = {r["run_id"] for r in api.get(f"/threads/{thread}/runs").json()}
    for tool in tools:
        response = api.get(f'/app/evidence/{tool["evidence_id"]}')
        response.raise_for_status()
        assert response.json()["thread_id"] == thread
        assert response.json()["tool_call_id"] == "phase-a-events-1"
        assert response.json()["run_id"] in run_ids
    # Re-entry reads the same durable IDs and content, without another tool execution.
    assert history(api, thread)["messages"] == saved["messages"]


def test_real_protocol_fail_cancel_and_checkpoint_regenerate(api):
    failed = create(api)
    response = api.post(f"/threads/{failed}/runs/wait", json={"assistant_id": "agent",
        "input": {"messages": [{"type": "human", "content": "/fake-fail"}]}})
    response.raise_for_status()
    assert sync(api, failed)["status"] == "failed"
    assert all(m["role"] == "human" or m["status"] != "completed"
               for m in history(api, failed)["messages"])
    cancelled = create(api)
    response = api.post(f"/threads/{cancelled}/runs", json={"assistant_id": "agent",
        "input": {"messages": [{"type": "human", "content": "/fake-slow"}]}})
    response.raise_for_status()
    run = response.json()["run_id"]
    time.sleep(.3)
    response = api.post(f"/threads/{cancelled}/runs/{run}/cancel?wait=1&action=interrupt")
    response.raise_for_status()
    assert sync(api, cancelled)["status"] in {"cancelled", "interrupted", "partial"}
    assert all(m["role"] == "human" or m["status"] != "completed"
               for m in history(api, cancelled)["messages"])
    # A regular run followed by replay from a real parent checkpoint.
    thread = create(api)
    response = api.post(f"/threads/{thread}/runs/wait", json={"assistant_id": "agent",
        "input": {"messages": [{"type": "human", "content": "合成重生成"}]}})
    response.raise_for_status()
    sync(api, thread)
    before = history(api, thread)
    response = api.post(f"/threads/{thread}/history", json={"limit": 10})
    response.raise_for_status()
    parent = next(s["checkpoint"] for s in response.json()
                  if s.get("values", {}).get("messages", [{}])[-1].get("type") == "tool")
    response = api.post(f"/threads/{thread}/runs/wait", json={
        "assistant_id": "agent", "checkpoint": parent, "input": None})
    response.raise_for_status()
    sync(api, thread)
    after = history(api, thread)
    assert len(before["messages"]) == len(after["messages"]) == 2
    assert before["messages"][0]["source_message_id"] == after["messages"][0]["source_message_id"]
    assert before["messages"][1]["source_message_id"] != after["messages"][1]["source_message_id"]


def test_real_protocol_checkpoint_interrupt_resume_and_sse_reconnect(api):
    thread = create(api)
    response = api.post(f"/threads/{thread}/runs/wait", json={"assistant_id": "agent",
        "input": {"messages": [{"type": "human", "content": "合成暂停恢复"}]},
        "interrupt_before": ["llm"]})
    response.raise_for_status()
    state = api.get(f"/threads/{thread}/state").json()
    assert "llm" in state["next"]
    assert sync(api, thread)["status"] == "interrupted"
    response = api.post(f"/threads/{thread}/runs/wait", json={
        "assistant_id": "agent", "input": None, "checkpoint": state["checkpoint"],
        "interrupt_before": []})
    response.raise_for_status()
    assert sync(api, thread)["status"] == "completed"
    assert len(history(api, thread)["messages"]) == 2
    reconnect = create(api)
    response = api.post(f"/threads/{reconnect}/runs", json={"assistant_id": "agent",
        "input": {"messages": [{"type": "human", "content": "/fake-slow"}]},
        "stream_mode": ["messages", "updates"], "stream_resumable": True})
    response.raise_for_status()
    run = response.json()["run_id"]
    # Join after the Run is created (same operation used by SDK reconnectOnMount).
    with api.stream("GET", f"/threads/{reconnect}/runs/{run}/stream") as response:
        response.raise_for_status()
        body = "".join(response.iter_text())
        assert "event: messages" in body
    for _ in range(20):
        if api.get(f"/threads/{reconnect}").json()["status"] != "busy":
            break
        time.sleep(.1)
    assert sync(api, reconnect)["status"] == "completed"
    assert sync(api, reconnect)["added"] == 0
    assert len(history(api, reconnect)["messages"]) == 2
