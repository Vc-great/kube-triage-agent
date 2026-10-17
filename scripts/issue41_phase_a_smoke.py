"""隔离 Aegra + FakeModel + Mock MCP 协议 Smoke；仅合成数据。"""

import json
import os

import httpx


def run():
    base = os.environ.get("ISSUE41_API_URL", "http://127.0.0.1:12441")
    token = os.environ.get("ISSUE41_TEST_TOKEN", "")
    if not token or not base.startswith("http://127.0.0.1:"):
        raise SystemExit("仅允许本机隔离 API 与显式测试 Token")
    client = httpx.Client(base_url=base, headers={"x-api-key": token}, timeout=30)
    assistants = client.get("/assistants")
    assistants.raise_for_status()
    assert {item["graph_id"] for item in assistants.json()["assistants"]} == {
        "agent", "deep_diagnosis"}
    response = client.post("/threads", json={})
    response.raise_for_status()
    thread_id = response.json()["thread_id"]
    runs = []
    for round_index in (1, 2):
        body = {"assistant_id": "deep_diagnosis", "input": {"messages": [
            {"role": "user", "content": f"第{round_index}轮合成事件诊断"}]},
            "stream_mode": ["values", "messages"]}
        with client.stream("POST", f"/threads/{thread_id}/runs/stream", json=body) as stream:
            stream.raise_for_status()
            events = []
            for line in stream.iter_lines():
                if line.startswith("event: "):
                    events.append(line.removeprefix("event: "))
                if line.startswith("data: ") and events[-1] == "metadata":
                    runs.append(json.loads(line[6:])["run_id"])
        assert "error" not in events, events
        assert "values" in events and "end" in events, events
    state = client.get(f"/threads/{thread_id}/state")
    history = client.get(f"/threads/{thread_id}/history")
    state.raise_for_status()
    history.raise_for_status()
    messages = state.json()["values"]["messages"]
    calls = [call["id"] for message in messages if message["type"] == "ai"
             for call in message.get("tool_calls", [])]
    results = [message["tool_call_id"] for message in messages if message["type"] == "tool"]
    assert calls == results and len(calls) == 2, (calls, results)
    print(json.dumps({"thread_id": thread_id, "run_ids": runs,
                      "message_types": [message["type"] for message in messages],
                      "tool_call_ids_match": calls == results,
                      "history_entries": len(history.json())}, ensure_ascii=False))


if __name__ == "__main__":
    run()
