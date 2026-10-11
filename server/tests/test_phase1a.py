import asyncio

import pytest
from langchain_core.messages import HumanMessage

from kube_triage.graph import _route, parse_demo_command
from kube_triage.mcp_client import NAMESPACE, _display_result, validate_call
from kube_triage.mock_mcp import (
    check_namespace,
    check_pod,
    events_list,
    mcp,
    pods_get,
    pods_list_in_namespace,
    pods_log,
)


def test_deterministic_routing():
    assert parse_demo_command(f"pods {NAMESPACE}") == (
        "pods_list_in_namespace", {"namespace": NAMESPACE})
    assert parse_demo_command(f"pod {NAMESPACE} healthy-pod") == (
        "pods_get", {"namespace": NAMESPACE, "name": "healthy-pod"})
    assert parse_demo_command(f"events {NAMESPACE}") == (
        "events_list", {"namespace": NAMESPACE})
    assert parse_demo_command(f"logs {NAMESPACE} healthy-pod") == (
        "pods_log", {"namespace": NAMESPACE, "name": "healthy-pod", "tail": 20})
    assert _route({"messages": [HumanMessage(content="/approve-demo")]}) == "approval_prompt"
    assert _route({"messages": [HumanMessage(content=f"pods {NAMESPACE}")]}) == "tool_request"


@pytest.mark.parametrize("name,args", [
    ("pods_delete", {"namespace": NAMESPACE}),
    ("pods_list_in_namespace", {"namespace": "default"}),
    ("pods_list_in_namespace", {"namespace": NAMESPACE, "extra": True}),
    ("events_list", {"namespace": NAMESPACE, "fieldSelector": "type=Warning"}),
    ("pods_get", {"namespace": NAMESPACE, "name": ""}),
    ("pods_log", {"namespace": NAMESPACE, "name": "healthy-pod", "tail": 0}),
    ("pods_log", {"namespace": NAMESPACE, "name": "healthy-pod", "tail": 101}),
    ("pods_log", {"namespace": NAMESPACE, "name": "healthy-pod", "tail": True}),
])
def test_client_policy_denies(name, args):
    with pytest.raises(ValueError):
        validate_call(name, args)


def test_server_policy_and_fixtures():
    for namespace in ("", "default", "kube-system"):
        with pytest.raises(ValueError):
            check_namespace(namespace)
    with pytest.raises(ValueError):
        check_pod("")
    assert pods_list_in_namespace(NAMESPACE)["mock"] is True
    assert pods_get(NAMESPACE, "healthy-pod")["source"] == "static-fixture"
    assert events_list(NAMESPACE)["mock"] is True
    assert "database unavailable" in pods_log(NAMESPACE, "crashloop-pod", 2)["logs"]
    for tail in (0, 101, True):
        with pytest.raises(ValueError):
            pods_log(NAMESPACE, "healthy-pod", tail)
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        asyncio.run(mcp._tool_manager.call_tool(
            "pods_list_in_namespace", {"namespace": NAMESPACE, "extra": True}))


def test_native_result_is_bounded(monkeypatch):
    from kube_triage import mcp_client

    monkeypatch.setattr(mcp_client, "MAX_RESULT_CHARS", 8)
    assert _display_result([{"type": "text", "text": "123456789"}]) == "12345678\n[结果已截断]"


def test_mcp_timeout_and_error_classes(monkeypatch):
    from langchain_core.tools import ToolException

    from kube_triage import mcp_client

    class SlowTool:
        async def ainvoke(self, _args):
            await asyncio.sleep(1)

    async def fake_tools():
        return {"pods_list_in_namespace": SlowTool()}

    monkeypatch.setattr(mcp_client, "_allowed_tools", fake_tools)
    monkeypatch.setattr(mcp_client, "MCP_TIMEOUT_SECONDS", 0.01)
    result = asyncio.run(mcp_client.call_tool("pods_list_in_namespace", {"namespace": NAMESPACE}))
    assert result["error_type"] == "timeout"
    async def disconnected():
        raise ConnectionError("mock unavailable")

    monkeypatch.setattr(mcp_client, "_allowed_tools", disconnected)
    result = asyncio.run(mcp_client.call_tool("pods_list_in_namespace", {"namespace": NAMESPACE}))
    assert result["error_type"] == "connection"
    assert "连接失败" in result["error"]
    assert mcp_client._error_type(ExceptionGroup("network", [ConnectionError()]))[0] == "connection"
    assert mcp_client._error_type(ToolException("forbidden: 403"))[0] == "forbidden"
    assert mcp_client._error_type(ToolException("Unauthorized: 401"))[0] == "unauthorized"
    assert mcp_client._error_type(ToolException("not found: 404"))[0] == "not_found"


def test_authentication(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "unit-test-secret")
    from kube_triage import auth as module

    monkeypatch.setattr(module, "EXPECTED_TOKEN", "unit-test-secret")
    assert asyncio.run(module.authenticate({"X-Api-Key": "unit-test-secret"}))["identity"] == "demo-user"
    for headers in ({}, {"x-api-key": "wrong"}):
        with pytest.raises(ValueError):
            asyncio.run(module.authenticate(headers))
