"""Phase A：仅使用合成模型与 MCP 回执。"""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import Field

from kube_triage import deep_diagnosis as deep
from kube_triage.deep_diagnosis_fake import ProtocolFakeModel


class FakeChatOpenAI(ChatOpenAI):
    replies: list[AIMessage] = Field(default_factory=list)
    seen_tools: list[list[str]] = Field(default_factory=list)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        tools = kwargs.get("tools", [])
        self.seen_tools.append([item["function"]["name"] for item in tools])
        reply = self.replies.pop(0)
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _model(*replies):
    return FakeChatOpenAI(model="phase-a-fake", api_key="synthetic-test-only",
                          replies=list(replies), seen_tools=[])


def test_visible_tools_and_parallel_ids(monkeypatch):
    seen = []

    async def mock_call(name, args, thread_id=None):
        seen.append((name, args))
        return {"ok": True, "result": "合成证据"}

    monkeypatch.setattr(deep, "call_tool", mock_call)
    model = _model(AIMessage(content="", tool_calls=[
        {"name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": "a"}, "id": "a1"},
        {"name": "events_list", "args": {"namespace": "kube-triage-demo"}, "id": "b2"},
    ]), AIMessage(content="观察：合成回执；推断：无；未知：真实状态。"))
    result = asyncio.run(deep.build_graph(model).ainvoke(
        {"messages": [HumanMessage(content="合成诊断")]}))
    assert all(set(names) == deep.ALLOWED_TOOLS for names in model.seen_tools)
    assert len(seen) == 2
    ai_ids = {c["id"] for m in result["messages"] if isinstance(m, AIMessage)
              for c in m.tool_calls}
    tool_ids = {m.tool_call_id for m in result["messages"] if isinstance(m, ToolMessage)}
    assert ai_ids == tool_ids == {"a1", "b2"}


def test_zero_tool_answer():
    model = _model(AIMessage(content="证据不足；当前状态未知。"))
    result = asyncio.run(deep.build_graph(model).ainvoke(
        {"messages": [HumanMessage(content="合成诊断")]}))
    assert not any(isinstance(m, ToolMessage) for m in result["messages"])
    assert result["messages"][-1].content == "证据不足；当前状态未知。"


def test_reader_failure_is_error(monkeypatch):
    async def mock_call(name, args, thread_id=None):
        return {"ok": False, "error_type": "forbidden", "error": "403"}

    monkeypatch.setattr(deep, "call_tool", mock_call)
    model = _model(AIMessage(content="", tool_calls=[
        {"name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": "a"}, "id": "fail"},
    ]), AIMessage(content="Reader 403；当前状态与根因未核验。"))
    result = asyncio.run(deep.build_graph(model).ainvoke(
        {"messages": [HumanMessage(content="合成诊断")]}))
    tool = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool.status == "error" and json.loads(tool.content)["ok"] is False


def test_cross_namespace_never_reaches_mcp(monkeypatch):
    async def forbidden(*args):
        raise AssertionError("跨 Namespace 不得调用 MCP")

    monkeypatch.setattr(deep, "call_tool", forbidden)
    model = _model(AIMessage(content="", tool_calls=[
        {"name": "pods_get", "args": {"namespace": "default", "name": "a"}, "id": "bad"},
    ]), AIMessage(content="参数拒绝；未核验。"))
    result = asyncio.run(deep.build_graph(model).ainvoke(
        {"messages": [HumanMessage(content="合成诊断")]}))
    assert next(m for m in result["messages"] if isinstance(m, ToolMessage)).status == "error"


def test_unknown_harness_tool_is_not_executable():
    boundary = deep.ReaderBoundary()
    from types import SimpleNamespace

    request = SimpleNamespace(tool_call={"name": "write_file", "id": "blocked", "args": {}},
                              state={"messages": [HumanMessage(content="合成诊断")]})
    async def forbidden(_request):
        raise AssertionError("Harness 工具不得执行")

    result = asyncio.run(boundary.awrap_tool_call(request, forbidden))
    assert result.status == "error" and result.tool_call_id == "blocked"


def test_parallel_budget_is_bounded():
    boundary = deep.ReaderBoundary()
    from types import SimpleNamespace

    previous = []
    for i in range(5):
        previous.append(AIMessage(content="", tool_calls=[
            {"name": "events_list", "args": {"namespace": "kube-triage-demo"},
             "id": f"old-{i}"}]))
        previous.append(ToolMessage(content="{}", tool_call_id=f"old-{i}"))
    latest = AIMessage(content="", tool_calls=[
        {"name": "events_list", "args": {"namespace": "kube-triage-demo"}, "id": "six"},
        {"name": "events_list", "args": {"namespace": "kube-triage-demo"}, "id": "seven"},
    ])
    state = {"messages": [HumanMessage(content="合成诊断"), *previous, latest]}
    async def allowed(request):
        return ToolMessage(content='{"ok": true, "result": "合成"}',
                           tool_call_id=request.tool_call["id"])

    first = asyncio.run(boundary.awrap_tool_call(SimpleNamespace(
        tool_call=latest.tool_calls[0], state=state), allowed))
    second = asyncio.run(boundary.awrap_tool_call(SimpleNamespace(
        tool_call=latest.tool_calls[1], state=state), allowed))
    assert first.status == "success" and second.status == "error"


def test_protocol_fake_stream_has_no_provider_client(monkeypatch):
    async def mock_call(name, args, thread_id=None):
        return {"ok": True, "result": "合成事件"}

    monkeypatch.setattr(deep, "call_tool", mock_call)
    model = ProtocolFakeModel()
    assert not isinstance(model, ChatOpenAI)

    async def collect():
        values = []
        async for event in deep.build_graph(model).astream(
                {"messages": [HumanMessage(content="合成诊断")]}, stream_mode="values"):
            values.append(event)
        return values

    values = asyncio.run(collect())
    assert any(isinstance(m, ToolMessage) for m in values[-1]["messages"])
    assert "合成 Mock 回执" in values[-1]["messages"][-1].content


def test_empty_reader_result_is_not_success():
    from types import SimpleNamespace

    call = {"name": "events_list", "args": {"namespace": "kube-triage-demo"},
            "id": "empty"}
    state = {"messages": [HumanMessage(content="合成"), AIMessage(content="", tool_calls=[call])]}
    request = SimpleNamespace(tool_call=call, state=state)

    async def empty(_request):
        return ToolMessage(content='{"ok": true, "result": ""}', tool_call_id="empty")

    result = asyncio.run(deep.ReaderBoundary().awrap_tool_call(request, empty))
    assert result.status == "error" and json.loads(result.content)["ok"] is False


@pytest.mark.parametrize("error_type", ["unauthorized", "forbidden", "not_found",
                                         "timeout", "connection", "server_error"])
def test_reader_errors_are_not_success(error_type):
    from types import SimpleNamespace

    call = {"name": "events_list", "args": {"namespace": "kube-triage-demo"},
            "id": "error"}
    state = {"messages": [HumanMessage(content="合成"), AIMessage(content="", tool_calls=[call])]}
    request = SimpleNamespace(tool_call=call, state=state)

    async def failed(_request):
        return ToolMessage(content=json.dumps({"ok": False, "error_type": error_type}),
                           tool_call_id="error")

    result = asyncio.run(deep.ReaderBoundary().awrap_tool_call(request, failed))
    assert result.status == "error" and json.loads(result.content)["error_type"] == error_type


def test_mismatched_tool_message_id_is_rejected():
    from types import SimpleNamespace

    call = {"name": "events_list", "args": {"namespace": "kube-triage-demo"},
            "id": "expected"}
    state = {"messages": [HumanMessage(content="合成"), AIMessage(content="", tool_calls=[call])]}

    async def mismatched(_request):
        return ToolMessage(content='{"ok": true, "result": "伪成功"}', tool_call_id="wrong")

    result = asyncio.run(deep.ReaderBoundary().awrap_tool_call(
        SimpleNamespace(tool_call=call, state=state), mismatched))
    assert result.status == "error" and result.tool_call_id == "expected"


def test_seven_parallel_calls_execute_at_most_six(monkeypatch):
    seen = []

    async def mock_call(name, args, thread_id=None):
        seen.append(name)
        return {"ok": True, "result": "合成事件"}

    monkeypatch.setattr(deep, "call_tool", mock_call)
    calls = [{"name": "events_list", "args": {"namespace": "kube-triage-demo"},
              "id": f"read-{i}"} for i in range(7)]
    model = _model(AIMessage(content="", tool_calls=calls),
                   AIMessage(content="证据预算已用尽；未知：真实状态。"))
    result = asyncio.run(deep.build_graph(model).ainvoke(
        {"messages": [HumanMessage(content="合成诊断")]}))
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(seen) == 6 and len(tool_messages) == 7
    assert tool_messages[-1].status == "error" and tool_messages[-1].tool_call_id == "read-6"


def test_forced_harness_write_call_is_rejected_by_graph():
    model = _model(AIMessage(content="", tool_calls=[
        {"name": "write_file", "args": {"file_path": "/x", "content": "bad"},
         "id": "force-write"},
    ]), AIMessage(content="未知：未读取集群。"))
    result = asyncio.run(deep.build_graph(model).ainvoke(
        {"messages": [HumanMessage(content="合成诊断")]}))
    tool = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool.status == "error" and tool.tool_call_id == "force-write"
    assert not result.get("files")
