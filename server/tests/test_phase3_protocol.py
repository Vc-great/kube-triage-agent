"""P3-B/C：真实实验 Profile 的同应用 History/Evidence HTTP 与 PG 关联。"""

import asyncio
import json
import os
import time
from uuid import uuid4

import httpx
import pytest
from test_app_protocol import create, history, sync

from kube_triage import app_storage

PROFILE = os.getenv("ISSUE78_PHASE3_PROFILE")
pytestmark = pytest.mark.skipif(not PROFILE, reason="requires isolated Phase 3 experiment API")


@pytest.fixture
def api():
    assert PROFILE in {"b1", "skills"}
    base = os.environ["ISSUE78_TEST_API_URL"]
    assert base in {"http://127.0.0.1:12079", "http://localhost:12079",
                   "http://127.0.0.1:12089", "http://localhost:12089"}
    with httpx.Client(base_url=base, headers={"x-api-key": os.environ["DEMO_API_TOKEN"]},
                      timeout=60) as client:
        yield client


@pytest.mark.parametrize("graph", ["deep_diagnosis", "deep_diagnosis_planning",
                                  "deep_diagnosis_skills"])
def test_experiment_history_sse_evidence_and_thread_isolation(api, graph):
    if (PROFILE == "skills") != (graph == "deep_diagnosis_skills"):
        pytest.skip("graph belongs to the other isolated profile")
    thread = create(api)
    evidence_ids = []
    for turn in range(2):
        body = {"assistant_id": graph, "input": {"messages": [
            {"type": "human", "id": str(uuid4()), "content": "CrashLoopBackOff"}]},
            "stream_mode": ["values", "messages", "updates"], "on_disconnect": "continue"}
        with api.stream("POST", f"/threads/{thread}/runs/stream", json=body) as response:
            response.raise_for_status()
            events = "".join(response.iter_text())
        assert "event: messages" in events and "event: updates" in events
        assert "event: error" not in events
        for _ in range(40):
            if api.get(f"/threads/{thread}").json()["status"] != "busy":
                break
            time.sleep(.1)
        assert sync(api, thread)["status"] == "completed"
        assert sync(api, thread)["added"] == 0
        saved = history(api, thread)
        assert len(saved["messages"]) == 2 * (turn + 1)
        assert all(m["status"] == "completed" for m in saved["messages"])
    state = api.get(f"/threads/{thread}/state").json()
    run_ids = {r["run_id"] for r in api.get(f"/threads/{thread}/runs").json()}
    tools = [m for m in state["values"]["messages"] if m["type"] == "tool"]
    for tool in tools:
        if tool["name"] not in {"events_list", "pods_get", "pods_list_in_namespace", "pods_log"}:
            assert "evidence_id" not in tool["content"]
            continue
        payload = json.loads(tool["content"])
        response = api.get(f'/app/evidence/{payload["evidence_id"]}')
        response.raise_for_status()
        row = response.json()
        assert row["graph_id"] == graph and row["thread_id"] == thread
        assert row["tool_call_id"] == tool["tool_call_id"]
        assert row["run_id"] is None or row["run_id"] in run_ids
        assert row["sha256"] == app_storage.digest(row["payload"])
        assert payload["evidence_persisted"] and row["status"] == "success"
        evidence_ids.append(row["id"])
    assert len(set(evidence_ids)) == (8 if PROFILE == "skills" else 2)
    if PROFILE == "skills":
        assert any(m["name"] == "read_file" for m in tools)
    first = api.get(f"/app/history/threads/{thread}/messages?limit=1").json()
    rest = api.get(f"/app/history/threads/{thread}/messages", params={
        "limit": 100, "cursor": first["next_cursor"], "checkpoint": first["checkpoint_id"]}).json()
    assert first["messages"] + rest["messages"] == saved["messages"]
    assert history(api, thread) == saved  # refresh/re-entry, stable IDs
    other = create(api)
    assert history(api, other)["messages"] == []
    assert api.post("/app/history/sync", json={"thread_id": other}).json()["status"] == "legacy"
    assert history(api, thread) == saved

    async def sql():
        async with await app_storage.connect() as conn:
            rows = await (await conn.execute(
                "SELECT id,graph_id FROM app_evidence WHERE thread_id=%s", (thread,))).fetchall()
            assert {str(r["id"]) for r in rows} == set(evidence_ids)
            assert all(r["graph_id"] == graph for r in rows)
            row = await (await conn.execute(
                "SELECT graph_id FROM app_conversations WHERE thread_id=%s", (thread,))).fetchone()
            assert row["graph_id"] == graph
    asyncio.run(sql())
    # The same custom auth protects both protocol and application routes.
    with httpx.Client(base_url=os.environ["ISSUE78_TEST_API_URL"]) as anonymous:
        assert anonymous.get(f"/app/evidence/{evidence_ids[0]}").status_code in {401, 403}
        assert anonymous.post("/app/history/sync", json={"thread_id": thread}).status_code in {401, 403}
