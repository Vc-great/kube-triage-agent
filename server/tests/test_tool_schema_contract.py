"""Offline contract between model-visible tools and native MCP execution."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from kube_triage import graph, mcp_client


class NativeTool:
    def __init__(self, name):
        self.name = name
        # Reproduce the Reader schema that caused M1 to generate denied selectors.
        self.args_schema = {"type": "object", "properties": {
            "namespace": {"type": "string"},
            "fieldSelector": {"type": "string"},
            "labelSelector": {"type": "string"},
        }}
        self.calls = []

    async def ainvoke(self, arguments):
        self.calls.append(arguments)
        return {"metadata": {"name": "demo", "namespace": mcp_client.NAMESPACE}}


def native_tools():
    return {name: NativeTool(name) for name in mcp_client.TOOL_ARGUMENTS}


def test_model_schema_exactly_matches_execution_contract():
    tools = native_tools()
    schemas = mcp_client.build_model_tool_schemas(tools)
    assert [tool["function"]["name"] for tool in schemas] == list(mcp_client.TOOL_ARGUMENTS)
    assert set(mcp_client.TOOL_ARGUMENTS) == mcp_client.ALLOWED_TOOLS
    for schema in schemas:
        function = schema["function"]
        required, optional = mcp_client.TOOL_ARGUMENTS[function["name"]]
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert parameters["required"] == list(required)
        assert list(parameters["properties"]) == [*required, *optional]
        assert parameters["additionalProperties"] is False
        assert parameters["properties"]["namespace"]["enum"] == [mcp_client.NAMESPACE]
        assert not {"fieldSelector", "labelSelector", "previous"} & parameters["properties"].keys()
        # Locked langchain-core conversion must preserve the provider-facing schema.
        assert convert_to_openai_tool(schema) == schema
    log_properties = schemas[-1]["function"]["parameters"]["properties"]
    assert log_properties["tail"]["type"] == "integer"
    assert (log_properties["tail"]["minimum"], log_properties["tail"]["maximum"]) == (1, 100)
    assert len(schemas) == 4


@pytest.mark.parametrize("name,args", [
    ("pods_list_in_namespace", {"namespace": mcp_client.NAMESPACE}),
    ("pods_get", {"namespace": mcp_client.NAMESPACE, "name": "demo-pod"}),
    ("events_list", {"namespace": mcp_client.NAMESPACE}),
    ("pods_log", {"namespace": mcp_client.NAMESPACE, "name": "demo-pod"}),
    ("pods_log", {"namespace": mcp_client.NAMESPACE, "name": "demo-pod",
                  "tail": 100, "container": "app"}),
])
def test_schema_allowed_calls_pass_validator(name, args):
    assert mcp_client.validate_call(name, args) is None


@pytest.mark.parametrize("name,args", [
    ("pods_list_in_namespace", {"namespace": mcp_client.NAMESPACE, "fieldSelector": "x"}),
    ("events_list", {"namespace": mcp_client.NAMESPACE, "labelSelector": "x"}),
    ("pods_get", {"namespace": mcp_client.NAMESPACE, "name": "demo", "previous": True}),
    ("pods_log", {"namespace": mcp_client.NAMESPACE, "name": "demo", "previous": True}),
    ("events_list", {"namespace": "default"}),
    ("resources_scale", {"namespace": mcp_client.NAMESPACE}),
    ("pods_log", {"namespace": mcp_client.NAMESPACE, "name": "demo", "tail": True}),
    ("pods_log", {"namespace": mcp_client.NAMESPACE, "name": "demo", "tail": 0}),
    ("pods_log", {"namespace": mcp_client.NAMESPACE, "name": "demo", "tail": 101}),
    ("pods_get", {"namespace": mcp_client.NAMESPACE, "name": "bad/name"}),
])
def test_schema_disallowed_calls_fail_validator(name, args):
    with pytest.raises((TypeError, ValueError)):
        mcp_client.validate_call(name, args)


@pytest.mark.parametrize("names", [
    ["pods_get"],
    [*mcp_client.TOOL_ARGUMENTS, "resources_scale"],
    ["pods_get", "events_list", "pods_log", "resources_scale"],
])
def test_wrong_discovery_fails_closed(names):
    with pytest.raises(RuntimeError, match="tools/list mismatch"):
        mcp_client.build_model_tool_schemas({name: SimpleNamespace(name=name) for name in names})


@pytest.mark.parametrize("args,expected_ok", [
    ({"namespace": mcp_client.NAMESPACE}, True),
    ({"namespace": mcp_client.NAMESPACE, "fieldSelector": "metadata.name=demo"}, False),
])
def test_graph_binds_narrow_schema_but_executes_native_reader(monkeypatch, args, expected_ok):
    tools = native_tools()
    captured = []

    class FakeModel:
        def bind_tools(self, schemas):
            captured.extend(schemas)
            return self

        async def ainvoke(self, _messages):
            if not hasattr(self, "called"):
                self.called = True
                return AIMessage(content="", tool_calls=[{
                    "name": "pods_list_in_namespace", "args": args, "id": "call-1"}])
            return AIMessage(content="查询完成" if expected_ok else "参数被拒绝，证据不足")

    async def discovered():
        return tools

    model = FakeModel()
    monkeypatch.setattr(graph, "chat_model", lambda: model)
    monkeypatch.setattr(graph, "_allowed_tools", discovered)
    monkeypatch.setattr(mcp_client, "_allowed_tools", discovered)
    messages = asyncio.run(graph.graph.ainvoke({"messages": [HumanMessage(content="调查 demo")]},
                                             {"recursion_limit": 25}))["messages"]
    tool_message = next(message for message in messages if isinstance(message, ToolMessage))
    result = json.loads(tool_message.content)
    assert tool_message.tool_call_id == "call-1"
    assert result["ok"] is expected_ok
    assert (result.get("error_type") == "policy") is (not expected_ok)
    assert tools["pods_list_in_namespace"].calls == ([args] if expected_ok else [])
    assert [item["function"]["name"] for item in captured[:4]] == list(mcp_client.TOOL_ARGUMENTS)
    assert captured[0]["function"]["parameters"]["properties"].keys() == {"namespace"}
