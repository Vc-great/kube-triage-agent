"""Aegra B1 protocol Smoke：要求隔离 localhost API 与合成 Mock MCP。"""

import json
import os

import httpx


def run():
    base = os.environ.get("ISSUE41_API_URL", "http://127.0.0.1:22441")
    token = os.environ.get("ISSUE41_TEST_TOKEN", "")
    if not token or not base.startswith("http://127.0.0.1:"):
        raise SystemExit("仅允许本机隔离 API 与显式合成测试 Token")
    client = httpx.Client(base_url=base, headers={"x-api-key": token}, timeout=30)
    assistants = client.get("/assistants")
    assistants.raise_for_status()
    graph_ids = {item["graph_id"] for item in assistants.json()["assistants"]}
    assert {"deep_diagnosis", "deep_diagnosis_planning"} <= graph_ids

    thread = client.post("/threads", json={})
    thread.raise_for_status()
    thread_id = thread.json()["thread_id"]
    events = []
    observed_plan_states = []
    reconnect_cursor = None
    resumed_event_count = 0
    for run_index, (graph_id, prompt) in enumerate((
        ("deep_diagnosis_planning", "执行一次复杂合成只读调查"),
        ("deep_diagnosis_planning", "你好，新一轮简单问候"),
    )):
        body = {"assistant_id": graph_id, "input": {"messages": [
            {"role": "user", "content": prompt},
        ]}, "stream_mode": ["values", "messages"], "stream_resumable": run_index == 0,
            "on_disconnect": "continue"}
        last_event_id = None
        run_id = None
        disconnected = False
        with client.stream("POST", f"/threads/{thread_id}/runs/stream", json=body) as stream:
            stream.raise_for_status()
            current_event = None
            seen_values = []
            for line in stream.iter_lines():
                if line.startswith("id: "):
                    last_event_id = line.removeprefix("id: ")
                elif line.startswith("event: "):
                    current_event = line.removeprefix("event: ")
                    events.append(current_event)
                elif line.startswith("data: ") and current_event == "values":
                    value = json.loads(line[6:])
                    seen_values.append(value)
                    todos = value.get("todos") if isinstance(value, dict) else None
                    if isinstance(todos, list) and todos:
                        observed_plan_states.append(todos)
                    if run_index == 0 and not disconnected:
                        disconnected = True
                        break
                elif line.startswith("data: ") and current_event == "metadata":
                    run_id = json.loads(line[6:]).get("run_id")
        assert "error" not in events and "values" in events
        assert seen_values
        if run_index == 0:
            assert last_event_id and run_id, "可重连 SSE 必须提供事件与 Run ID"
            reconnect_cursor = last_event_id
            resumed_ids = []
            resumed_events = []
            current_event = None
            with client.stream("GET", f"/threads/{thread_id}/runs/{run_id}/stream",
                               headers={"Last-Event-ID": last_event_id}) as resumed:
                resumed.raise_for_status()
                for line in resumed.iter_lines():
                    if line.startswith("id: "):
                        resumed_ids.append(line.removeprefix("id: "))
                    elif line.startswith("event: "):
                        current_event = line.removeprefix("event: ")
                        resumed_events.append(current_event)
                    elif line.startswith("data: ") and current_event == "values":
                        value = json.loads(line[6:])
                        todos = value.get("todos") if isinstance(value, dict) else None
                        if isinstance(todos, list) and todos:
                            observed_plan_states.append(todos)
            assert resumed_events and "end" in resumed_events
            assert last_event_id not in resumed_ids, "重连不得重放游标指向的 SSE 事件"
            resumed_event_count = len(resumed_events)
            assert observed_plan_states and any(
                any(item.get("status") == "completed" for item in todos if isinstance(item, dict))
                for todos in observed_plan_states
            ), "重连 SSE 必须包含真实结构化 Todo 状态更新"
        else:
            assert "end" in events

    state_response = client.get(f"/threads/{thread_id}/state")
    state_response.raise_for_status()
    values = state_response.json()["values"]
    messages = values["messages"]
    calls = [call["id"] for message in messages if message["type"] == "ai"
             for call in message.get("tool_calls", [])]
    replies = [message["tool_call_id"] for message in messages if message["type"] == "tool"]
    assert calls == replies, (calls, replies)
    assert values.get("todos") == [], "新 Human 轮必须清空前一轮计划"
    assert any("b1-todo-plan" in ident for ident in calls)
    assert any("b1-reader-events" in ident for ident in calls)
    baseline_thread = client.post("/threads", json={})
    baseline_thread.raise_for_status()
    baseline_thread_id = baseline_thread.json()["thread_id"]
    baseline_response = client.post(f"/threads/{baseline_thread_id}/runs/wait", json={
        "assistant_id": "deep_diagnosis", "input": {"messages": [
            {"role": "user", "content": "执行 Baseline 合成只读事件检查"},
        ]}, "stream_mode": ["values"],
    })
    baseline_response.raise_for_status()
    baseline_state = client.get(f"/threads/{baseline_thread_id}/state")
    baseline_state.raise_for_status()
    baseline_messages = baseline_state.json()["values"]["messages"]
    baseline_calls = [call for message in baseline_messages if message["type"] == "ai"
                      for call in message.get("tool_calls", [])]
    baseline_replies = [message["tool_call_id"] for message in baseline_messages
                        if message["type"] == "tool"]
    assert {call["name"] for call in baseline_calls} <= {
        "pods_list_in_namespace", "pods_get", "events_list", "pods_log",
    }
    assert all(call["name"] != "write_todos" for call in baseline_calls)
    assert [call["id"] for call in baseline_calls] == baseline_replies
    cancel_thread = client.post("/threads", json={})
    cancel_thread.raise_for_status()
    cancel_thread_id = cancel_thread.json()["thread_id"]
    cancel_run_id = None
    cancel_response = None
    cancel_body = {"assistant_id": "deep_diagnosis_planning", "input": {"messages": [
        {"role": "user", "content": "执行可取消的合成复杂调查"},
    ]}, "stream_mode": ["values"], "on_disconnect": "continue"}
    with client.stream("POST", f"/threads/{cancel_thread_id}/runs/stream",
                       json=cancel_body) as stream:
        stream.raise_for_status()
        current_event = None
        for line in stream.iter_lines():
            if line.startswith("event: "):
                current_event = line.removeprefix("event: ")
            elif line.startswith("data: ") and current_event == "metadata":
                cancel_run_id = json.loads(line[6:]).get("run_id")
                cancel_response = client.post(
                    f"/threads/{cancel_thread_id}/runs/{cancel_run_id}/cancel",
                    params={"action": "interrupt", "wait": 1},
                )
                break
    assert cancel_run_id and cancel_response is not None
    cancel_response.raise_for_status()
    status_response = client.get(f"/threads/{cancel_thread_id}/runs/{cancel_run_id}")
    status_response.raise_for_status()
    cancel_status = status_response.json().get("status")
    assert cancel_status == "interrupted", cancel_status
    print(json.dumps({"thread_id": thread_id, "graph_ids": sorted(graph_ids),
                      "event_types": events, "tool_ids_paired": calls == replies,
                      "reader_and_todo_calls": calls,
                      "baseline_reader_only": True,
                      "observed_plan_state_count": len(observed_plan_states),
                      "last_event_id": reconnect_cursor,
                      "resumed_event_count": resumed_event_count,
                      "cancel_status": cancel_status,
                      "new_turn_todos_reset": values.get("todos") == []}, ensure_ascii=False))


if __name__ == "__main__":
    run()
