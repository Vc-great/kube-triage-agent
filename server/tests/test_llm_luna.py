"""Offline checks for the development-only Luna configuration boundary."""

import asyncio
import json

from langchain_core.messages import AIMessage, ToolMessage

from kube_triage import graph, llm


def test_luna_development_uses_responses_high_without_exposing_key(monkeypatch):
    captured = {}
    monkeypatch.setenv("TRIAGE_ENV", "development")
    monkeypatch.setenv("LLM_MODEL", "gpt-6-luna")
    monkeypatch.setenv("LLM_API_KEY", "private-test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8317/v1")
    monkeypatch.setattr(llm, "ChatOpenAI", lambda **kwargs: captured.update(kwargs) or object())

    llm.chat_model()

    assert captured["model"] == "gpt-6-luna"
    assert captured["use_responses_api"] is True
    assert captured["reasoning"] == {"effort": "high"}
    assert captured["timeout"] == 30 and captured["max_retries"] == 1
    assert "private-test-key" not in repr({k: v for k, v in captured.items()
                                            if k != "api_key"})


def test_other_model_and_production_preserve_original_api(monkeypatch):
    captured = []
    monkeypatch.setenv("LLM_API_KEY", "private-test-key")
    monkeypatch.setattr(llm, "ChatOpenAI", lambda **kwargs: captured.append(kwargs) or object())
    for environment, model in (("development", "deepseek-flash"),
                               ("production", "gpt-6-luna")):
        monkeypatch.setenv("TRIAGE_ENV", environment)
        monkeypatch.setenv("LLM_MODEL", model)
        llm.chat_model()
    for options in captured:
        assert "use_responses_api" not in options
        assert "reasoning" not in options
        assert options["timeout"] == 30 and options["max_retries"] == 1


def test_tool_call_id_is_preserved_in_tool_message(monkeypatch):
    async def fake_call(name, args, thread_id):
        assert (name, args, thread_id) == (
            "pods_get", {"namespace": "kube-triage-demo", "name": "example"}, "thread-1")
        return {"ok": True, "result": "metadata: {}"}

    monkeypatch.setattr(graph, "call_tool", fake_call)
    request = AIMessage(content="", name="triage_llm", tool_calls=[{
        "id": "call-1", "name": "pods_get",
        "args": {"namespace": "kube-triage-demo", "name": "example"},
    }])
    result = asyncio.run(graph._execute_tool(
        {"messages": [request]}, {"configurable": {"thread_id": "thread-1"}}))
    reply = result["messages"][0]
    assert isinstance(reply, ToolMessage)
    assert reply.tool_call_id == request.tool_calls[0]["id"]
    assert json.loads(reply.content)["ok"] is True
