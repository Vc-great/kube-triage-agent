import asyncio

import pytest
from langchain_core.messages import HumanMessage

from kube_triage.graph import _route, parse_demo_command
from kube_triage.mcp_client import normalize_result, validate_call
from kube_triage.mock_mcp import check_namespace, check_pod, get_pod_logs, list_pods


def test_deterministic_routing():
    assert parse_demo_command("pods demo") == ("list_pods", {"namespace": "demo"})
    assert parse_demo_command("events demo crashloop-pod")[0] == "get_pod_events"
    assert parse_demo_command("logs demo crashloop-pod")[0] == "get_pod_logs"
    assert _route({"messages": [HumanMessage(content="/approve-demo")]}) == "approval_prompt"
    assert _route({"messages": [HumanMessage(content="pods demo")]}) == "tool_request"


@pytest.mark.parametrize("name,args", [
    ("delete_pod", {"namespace": "demo"}),
    ("list_pods", {"namespace": "default"}),
    ("list_pods", {"namespace": "kube-system"}),
    ("get_pod_events", {"namespace": "demo", "pod_name": ""}),
    ("get_pod_logs", {"namespace": "demo", "pod_name": "healthy-pod", "tail_lines": 0}),
    ("get_pod_logs", {"namespace": "demo", "pod_name": "healthy-pod", "tail_lines": 101}),
    ("get_pod_logs", {"namespace": "demo", "pod_name": "healthy-pod", "tail_lines": True}),
])
def test_adapter_policy_denies(name, args):
    with pytest.raises(ValueError):
        validate_call(name, args)


def test_server_policy_denies():
    for namespace in ("", "default", "kube-system"):
        with pytest.raises(ValueError):
            check_namespace(namespace)
    with pytest.raises(ValueError):
        check_pod("")
    check_namespace("demo")
    check_pod("healthy-pod")


def test_server_static_fixture_and_log_limit():
    assert list_pods("demo")["mock"] is True
    assert list_pods("demo")["source"] == "static-fixture"
    assert get_pod_logs("demo", "healthy-pod", 1)["truncated"] is True
    for tail_lines in (0, 101, True):
        with pytest.raises(ValueError):
            get_pod_logs("demo", "healthy-pod", tail_lines)


def test_adapter_unwraps_mcp_text_result():
    assert normalize_result([{"type": "text", "text": '{"mock": true}'}]) == {"mock": True}


def test_mcp_timeout_and_error_classes(monkeypatch):
    from langchain_core.tools import ToolException

    from kube_triage import mcp_client

    class SlowTool:
        async def ainvoke(self, _args):
            await asyncio.sleep(1)

    async def fake_tools():
        return {"list_pods": SlowTool()}

    monkeypatch.setattr(mcp_client, "_allowed_tools", fake_tools)
    monkeypatch.setattr(mcp_client, "MCP_TIMEOUT_SECONDS", 0.01)
    result = asyncio.run(mcp_client.call_tool("list_pods", {"namespace": "demo"}))
    assert result["error_type"] == "timeout"
    assert mcp_client._error_type(ExceptionGroup("network", [ConnectionError()]))[0] == "connection"
    assert mcp_client._error_type(ToolException("denied"))[0] == "tool_rejected"


def test_authentication(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "unit-test-secret")
    from kube_triage import auth as module

    monkeypatch.setattr(module, "EXPECTED_TOKEN", "unit-test-secret")
    assert asyncio.run(module.authenticate({"X-Api-Key": "unit-test-secret"}))["identity"] == "demo-user"
    for headers in ({}, {"x-api-key": "wrong"}):
        with pytest.raises(ValueError):
            asyncio.run(module.authenticate(headers))
