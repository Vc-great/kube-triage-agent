"""V2 冻结合成案例：独立 Aegra/PG + 真 HTTP/SSE，未启动时 NOT RUN。"""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

CASES = json.loads((Path(__file__).parent / "fixtures/issue72-review-cases.json").read_text())
READERS = {"pods_get", "pods_list_in_namespace", "events_list", "pods_log"}
pytestmark = pytest.mark.skipif(not os.getenv("ISSUE72_TEST_API_URL"), reason="需要隔离 Reviewer API/PG")


@pytest.fixture
def api():
    base = os.environ["ISSUE72_TEST_API_URL"]
    url = urlsplit(base)
    assert url.scheme == "http" and url.hostname == "127.0.0.1"
    assert url.port and url.path in {"", "/"} and not url.username and not url.password
    assert not url.query and not url.fragment
    with httpx.Client(base_url=base, headers={"x-api-key": "skills-demo-local-only"}, timeout=60) as c:
        response = c.get("/assistants")
        response.raise_for_status()
        assert {a["graph_id"] for a in response.json()["assistants"]} == {"deep_diagnosis_review"}
        yield c


def create(api):
    response = api.post("/threads", json={})
    response.raise_for_status()
    return response.json()["thread_id"]


def run(api, thread, prompt):
    started = time.monotonic()
    body = {"assistant_id": "deep_diagnosis_review", "input": {"messages": [
        {"type": "human", "id": str(uuid4()), "content": [{"type": "text", "text": prompt}]}]},
        "stream_mode": ["values", "messages", "updates"], "stream_subgraphs": True, "on_disconnect": "continue"}
    with api.stream("POST", f"/threads/{thread}/runs/stream", json=body) as response:
        response.raise_for_status()
        events = "".join(response.iter_text())
    assert "event: end" in events and "event: error" not in events, events[-2000:]
    assert '"status":"success"' in events
    state = api.get(f"/threads/{thread}/state")
    state.raise_for_status()
    assert state.json()["next"] == []
    return state.json()["values"]["messages"], time.monotonic() - started


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
@pytest.mark.parametrize("enabled", [False, True], ids=["OFF", "ON"])
def test_frozen_http_cases(api, case, enabled):
    messages, duration = run(api, create(api), case["prompt"] if enabled else
                             (case["prompt"] if case["id"] == "greeting" else case["prompt"] + " Reviewer OFF"))
    calls = [c for m in messages if m["type"] == "ai" for c in m.get("tool_calls", [])]
    tools = [m for m in messages if m["type"] == "tool"]
    assert [c["id"] for c in calls] == [m["tool_call_id"] for m in tools]
    assert len({c["id"] for c in calls}) == len(calls)
    assert sum(c["name"] in READERS for c in calls) == case["readers"]
    tasks = [m for m in tools if m["name"] == "task"]
    assert len(tasks) == (case["task"] if enabled else 0)
    assert all(c["name"] in READERS | {"task", "write_todos"} for c in calls)
    status = case["status"] if enabled or case["id"] == "greeting" else "UNREVIEWED"
    verdict = case["verdict"] if enabled else "UNKNOWN"
    final = messages[-1]["content"]
    assert f"review_status={status}" in final and f"verdict={verdict}" in final
    if case["readers"]:
        assert all(label in final for label in ["观察：", "推断：", "未知：", "evidence_refs"])
    if enabled and verdict in {"SUPPORTS", "CONTRADICTS"}:
        assert "review-pod" in final and "UID" in final
    if tasks:
        result = json.loads(tasks[0]["content"])
        assert result["review_status"] == status and result["verdict"] == verdict
        assert tasks[0]["status"] == ("error" if status == "FAILED" else "success")
    if case["id"] in {"forbidden", "timeout"}:
        pod = next(m for m in tools if m["name"] == "pods_get")
        assert json.loads(pod["content"])["error_type"] == (
            "forbidden" if case["id"] == "forbidden" else "timeout")
    print(json.dumps({"case": case["id"], "reviewer": "ON" if enabled else "OFF",
        "reader_count": case["readers"], "task_count": len(tasks), "paired": True,
        "status": status, "verdict": verdict, "seconds": round(duration, 3)}))


def test_completed_thread_turns_refresh_and_isolation(api):
    thread = create(api)
    first, _ = run(api, thread, "诊断 crashloop-pod CrashLoopBackOff")
    assert "verdict=SUPPORTS" in first[-1]["content"]
    second, _ = run(api, thread, "你好")
    assert second[:len(first)] == first
    assert "review_status=SKIPPED" in second[-1]["content"]
    assert "SUPPORTS" not in second[-1]["content"]
    assert sum(m.get("name") == "task" for m in second) == 1
    assert api.get(f"/threads/{thread}/state").json()["values"]["messages"] == second
    third, _ = run(api, thread, "诊断 imagepull-pod ImagePullBackOff")
    assert "verdict=SUPPORTS" in third[-1]["content"]
    assert "imagepull-pod" in third[-1]["content"]
    assert api.get(f"/threads/{thread}/history").status_code == 200
    other = create(api)
    assert not api.get(f"/threads/{other}/state").json()["values"].get("messages")
    assert api.get(f"/threads/{thread}/state").json()["values"]["messages"] == third
