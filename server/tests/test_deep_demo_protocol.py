"""SDK 实际 HTTP 边界：MockTransport，不发送任何真实 Provider 请求。"""

import asyncio
import json
import socket

import httpx2
import pytest
from langchain_core.messages import HumanMessage

from kube_triage import deep_diagnosis, deep_diagnosis_planning, llm


@pytest.mark.parametrize("planning", [False, True])
def test_sdk_graph_preserves_explicit_chat_completions(monkeypatch, planning):
    def denied(*_args, **_kwargs):
        raise AssertionError("协议测试禁止真实网络")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("EVAL_LUNA_RESPONSES_HIGH", "false")
    monkeypatch.setenv("LLM_MODEL", "gpt-6-luna")
    monkeypatch.setenv("LLM_API_KEY", "synthetic-unused")
    monkeypatch.setenv("LLM_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    requests = []

    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "gpt-6-luna"
        tools = {item["function"]["name"] for item in body["tools"]}
        expected = {"pods_list_in_namespace", "pods_get", "events_list", "pods_log"}
        assert tools == expected | ({"write_todos"} if planning else set())
        tool = "write_todos" if planning else "events_list"
        args = ({"todos": [{"content": "核对合成证据", "status": "in_progress"}]}
                if planning else {"namespace": "kube-triage-demo"})
        message = ({"role": "assistant", "content": None, "tool_calls": [{
            "id": "synthetic-call", "type": "function", "function": {
                "name": tool, "arguments": json.dumps(args)}}]} if len(requests) == 1 else {
                    "role": "assistant", "content": "观察：合成结果。推断与未知：真实集群未核验。"})
        if len(requests) == 2:
            assert any(m.get("tool_call_id") == "synthetic-call" for m in body["messages"])
        return httpx2.Response(200, json={
            "id": "synthetic-completion", "object": "chat.completion", "created": 1,
            "model": "gpt-6-luna", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    original = llm.ChatOpenAI

    async def run():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            def configured(**kwargs):
                assert kwargs["use_responses_api"] is False
                return original(**kwargs, http_async_client=client)

            monkeypatch.setattr(llm, "ChatOpenAI", configured)

            async def reader(*_args, **_kwargs):
                return {"ok": True, "result": "合成事件"}

            monkeypatch.setattr(deep_diagnosis, "call_tool", reader)
            module = deep_diagnosis_planning if planning else deep_diagnosis
            graph = module.build_graph()
            return await graph.ainvoke({"messages": [HumanMessage("你好，执行合成协议测试")]})

    result = asyncio.run(run())
    assert len(requests) == 2
    assert result["messages"][-1].content.startswith("观察")
    if planning:
        assert result["todos"] == [{"content": "核对合成证据", "status": "in_progress"}]
