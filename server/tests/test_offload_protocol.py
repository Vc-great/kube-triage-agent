"""Phase A：隔离 Aegra/PostgreSQL + Mock MCP 的真实 HTTP/SSE 与重载。"""

import json
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

from kube_triage.deep_diagnosis_offload_fake import NOTE

pytestmark = pytest.mark.skipif(not os.getenv("ISSUE69_TEST_API_URL"), reason="需要隔离 Notes Demo API/PG")


@pytest.fixture
def api():
    base = os.environ["ISSUE69_TEST_API_URL"]
    url = urlsplit(base)
    assert url.scheme == "http" and url.hostname == "127.0.0.1" and url.port
    assert url.path in {"", "/"} and not url.username and not url.password
    assert not url.query and not url.fragment
    with httpx.Client(base_url=base, headers={"x-api-key": "skills-demo-local-only"}, timeout=60) as client:
        response = client.get("/assistants")
        response.raise_for_status()
        assert {a["graph_id"] for a in response.json()["assistants"]} == {"deep_diagnosis_offload"}
        yield client


def create(api):
    response = api.post("/threads", json={})
    response.raise_for_status()
    return response.json()["thread_id"]


def run(api, thread, prompt):
    body = {"assistant_id": "deep_diagnosis_offload", "input": {"messages": [
        {"type": "human", "id": str(uuid4()), "content": [{"type": "text", "text": prompt}]}]},
        "stream_mode": ["values", "messages", "updates"], "on_disconnect": "continue"}
    values = []
    with api.stream("POST", f"/threads/{thread}/runs/stream", json=body) as response:
        response.raise_for_status()
        event = ""
        events = []
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
                events.append(event)
            elif line.startswith("data: ") and event == "values":
                values.append(json.loads(line[6:]))
    assert "end" in events and "error" not in events and values
    response = api.get(f"/threads/{thread}/state")
    response.raise_for_status()
    assert response.json()["next"] == []
    state = response.json()["values"]
    assert values[-1]["messages"] == state["messages"]
    messages = state["messages"]
    calls = [c for m in messages if m["type"] == "ai" for c in m.get("tool_calls", [])]
    tools = [m for m in messages if m["type"] == "tool"]
    assert [c["id"] for c in calls] == [m["tool_call_id"] for m in tools]
    assert len({c["id"] for c in calls}) == len(calls)
    return state, tools


def test_notes_sse_pg_completed_turns_refresh_and_new_thread(api):
    thread = create(api)
    first, tools = run(api, thread, "调查合成事件并保存笔记")
    assert [m["name"] for m in tools] == ["write_todos", "events_list", "write_file", "read_file",
                                           "ls", "grep", "write_todos"]
    assert all(m.get("status", "success") == "success" for m in tools)
    saved = first["files"][NOTE]["content"]
    assert "合成调查笔记" in saved and "非真实集群" in saved
    assert saved in tools[3]["content"] and NOTE in tools[4]["content"] and NOTE in tools[5]["content"]
    assert first["todos"][0]["status"] == "completed"
    # Fresh HTTP GET is the API used by a browser refresh; completed run only.
    assert api.get(f"/threads/{thread}/state").json()["values"]["files"] == first["files"]
    second, _ = run(api, thread, "刷新后读取笔记")
    assert second["files"] == first["files"]
    assert second["messages"][:len(first["messages"])] == first["messages"]
    assert saved in second["messages"][-1]["content"]
    third, _ = run(api, thread, "你好")
    assert third["files"] == first["files"] and third["todos"] == []
    assert api.get(f"/threads/{thread}/history").status_code == 200
    other = create(api)
    isolated, replies = run(api, other, "读取笔记")
    assert not isolated.get("files") and replies[0]["status"] == "error"
    assert "失败" in isolated["messages"][-1]["content"]
    assert api.get(f"/threads/{thread}/state").json()["values"]["files"] == first["files"]
    print(f"Thread={thread}; SSE/PG/write/read/ls/grep/refresh/3 turns/new Thread=PASS")


@pytest.mark.parametrize("prompt", ["读取不存在的笔记", "越界读取笔记"])
def test_file_failure_visible_over_sse(api, prompt):
    state, tools = run(api, create(api), prompt)
    assert len(tools) == 1 and tools[0]["status"] == "error"
    assert not state.get("files") and "失败" in state["messages"][-1]["content"]
    assert "已保存" not in state["messages"][-1]["content"]
