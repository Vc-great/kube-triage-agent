"""真实独立 Aegra HTTP/SSE + Mock MCP；未启动测试服务时明确 skip。"""

import json
import os
from urllib.parse import urlsplit

import httpx
import pytest


@pytest.mark.skipif(not os.getenv("ISSUE75_TEST_API_URL"), reason="需要隔离 Skills Demo 服务")
def test_skills_http_sse_and_completed_thread_history():
    base = os.environ["ISSUE75_TEST_API_URL"]
    url = urlsplit(base)
    assert url.scheme == "http" and url.hostname == "127.0.0.1"
    assert url.port and url.path in {"", "/"} and not url.username and not url.password
    assert not url.query and not url.fragment
    with httpx.Client(base_url=base, headers={"x-api-key": "skills-demo-local-only"}, timeout=60) as client:
        response = client.get("/assistants")
        response.raise_for_status()
        assert {a["graph_id"] for a in response.json()["assistants"]} == {"deep_diagnosis_skills"}
        for prompt, selected in [
            ("CrashLoopBackOff", "crashloop-diagnosis"),
            ("OOMKilled", "oom-diagnosis"),
            ("ImagePullBackOff", "imagepull-diagnosis"),
            ("你好", None),
        ]:
            response = client.post("/threads", json={})
            response.raise_for_status()
            thread = response.json()["thread_id"]
            body = {"assistant_id": "deep_diagnosis_skills", "input": {"messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}]},
                "stream_mode": ["values", "messages"],
                "on_disconnect": "continue"}
            events, values = [], []
            with client.stream("POST", f"/threads/{thread}/runs/stream", json=body) as stream:
                stream.raise_for_status()
                event = ""
                for line in stream.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                        events.append(event)
                    elif line.startswith("data: ") and event == "values":
                        values.append(json.loads(line[6:]))
            assert "end" in events and "error" not in events and values
            response = client.get(f"/threads/{thread}/state")
            response.raise_for_status()
            messages = response.json()["values"]["messages"]
            calls = [c for m in messages if m["type"] == "ai" for c in m.get("tool_calls", [])]
            tools = [m for m in messages if m["type"] == "tool"]
            assert [c["id"] for c in calls] == [m["tool_call_id"] for m in tools]
            assert not any(m.get("additional_kwargs", {}).get("lc_source") == "pinned_skill"
                           for m in messages)
            if selected:
                assert [c["name"] for c in calls] == ["read_file", "pods_list_in_namespace",
                                                     "pods_get", "events_list", "pods_log"]
                assert selected in calls[0]["args"]["file_path"]
                assert all(m.get("status", "success") == "success" for m in tools)
                assert "UNKNOWN" in messages[-1]["content"] and "UID=" in messages[-1]["content"]
            else:
                assert not calls
            if os.getenv("APP_EVIDENCE_ENABLED", "false") == "false":
                assert all("evidence_persisted" not in m["content"] for m in tools)
                assert client.get("/app/evidence/00000000-0000-0000-0000-000000000001").status_code == 404
            if os.getenv("APP_HISTORY_ENABLED", "false") == "false":
                assert client.post("/app/history/sync", json={"thread_id": thread}).status_code == 404
            # Ordinary new Human run from a completed checkpoint, never pending-run Resume.
            response = client.post(f"/threads/{thread}/runs/wait", json={
                "assistant_id": "deep_diagnosis_skills", "input": {"messages": [
                    {"role": "user", "content": "上轮结论是什么"}]}})
            response.raise_for_status()
            assert "上轮普通历史" in response.json()["messages"][-1]["content"]
            response = client.get(f"/threads/{thread}/state")
            response.raise_for_status()
            assert len(response.json()["values"]["messages"]) > len(messages)
