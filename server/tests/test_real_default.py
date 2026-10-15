"""Formal fail-closed checks and explicit offline MCP protocol contracts."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from kube_triage import config, graph, mcp_client, repair

ROOT = Path(__file__).parents[2]


@pytest.fixture
def formal(monkeypatch):
    for key in ("LLM_ENABLED", "REPAIR_SIMULATED", "REPAIR_ENABLED", "MCP_SERVER_URL",
                "LLM_MODEL", "LLM_API_KEY", "TRIAGE_ENV"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TRIAGE_ENV", "production")
    return monkeypatch


@pytest.mark.parametrize("missing", ["LLM_MODEL", "LLM_API_KEY"])
def test_missing_llm_fails_run_without_answer(formal, missing):
    formal.setenv("LLM_MODEL", "test-model")
    formal.setenv("LLM_API_KEY", "test-key")
    formal.delenv(missing)
    with pytest.raises(config.ConfigurationError, match="LLM 配置错误"):
        asyncio.run(graph.graph.ainvoke({"messages": [HumanMessage(content="调查 Pod")]}))


@pytest.mark.parametrize("url", ["", "http://mock-mcp:8000/mcp", "http://localhost:8000/mcp",
                                "http://k8s-mcp:8080/mcp?redirect=mock", "https://example.com/mcp"])
def test_reader_missing_or_unapproved_fails_before_transport(formal, url):
    formal.setenv("MCP_SERVER_URL", url)
    with pytest.raises(config.ConfigurationError, match="Reader 配置错误"):
        asyncio.run(mcp_client._allowed_tools())
    with pytest.raises(config.ConfigurationError):
        asyncio.run(mcp_client.call_tool("events_list", {"namespace": mcp_client.NAMESPACE}))


def test_reader_configuration_failure_fails_run(formal):
    formal.setenv("LLM_MODEL", "test-model")
    formal.setenv("LLM_API_KEY", "test-key")
    with pytest.raises(config.ConfigurationError, match="Reader 配置错误"):
        asyncio.run(graph.graph.ainvoke({"messages": [HumanMessage(content="调查")]}))


def test_production_rejects_simulation_and_legacy_llm_switch(formal):
    formal.setenv("REPAIR_SIMULATED", "true")
    for check in (config.validate_service, repair.simulated, repair.repair_enabled):
        with pytest.raises(config.ConfigurationError, match="禁止"):
            check()
    formal.setenv("REPAIR_SIMULATED", "false")
    formal.setenv("LLM_ENABLED", "false")
    with pytest.raises(config.ConfigurationError, match="已移除"):
        config.validate_llm()


def test_formal_compose_and_graph_have_no_demo_shortcuts():
    real = yaml.safe_load((ROOT / "infra/compose.yaml").read_text())
    testing = yaml.safe_load((ROOT / "infra/test.compose.yaml").read_text())
    assert not any("mock" in name for name in real["services"])
    api = real["services"]["api"]
    assert "k8s-mcp" in api["depends_on"] and "profiles" not in real["services"]["k8s-mcp"]
    assert "mock" not in api["environment"]["MCP_SERVER_URL"]
    assert api["environment"]["TRIAGE_ENV"] == "production"
    assert api["environment"]["REPAIR_ENABLED"] == "${REPAIR_ENABLED:-false}"
    assert set(graph.builder.nodes) == {
        "llm", "tools", "memory_retrieve", "repair_prepare", "repair_approval",
        "repair_execute",
        "memory_prepare", "memory_review", "memory_commit",
        "revoke_prepare", "revoke_review", "revoke_commit",
    }
    assert testing["services"]["api"]["environment"]["TRIAGE_ENV"] == "test"
    assert "k8s-mcp" not in testing["services"] and "repair-mcp" not in testing["services"]
    assert "kubeconfig" not in (ROOT / "infra/test.compose.yaml").read_text()
    assert "from kube_triage.auth import auth" in (ROOT / "server/Dockerfile").read_text()
    reader = (ROOT / "infra/k8s-mcp/config.toml").read_text()
    assert "read_only = true" in reader
    assert all(name in reader for name in mcp_client.ALLOWED_TOOLS)


def test_url_change_rebuilds_cached_tools_and_revalidates(formal):
    clients = []

    class Client:
        def __init__(self, connections, **_kwargs):
            clients.append(connections["kubernetes"]["url"])

        async def get_tools(self, **_kwargs):
            return [type("Tool", (), {"name": name})() for name in mcp_client.ALLOWED_TOOLS]

    formal.setattr(mcp_client, "MultiServerMCPClient", Client)
    formal.setattr(mcp_client, "_tools_url", None)
    formal.setattr(mcp_client, "_tools", None)
    formal.setenv("MCP_SERVER_URL", "http://k8s-mcp:8080/mcp")
    asyncio.run(mcp_client._allowed_tools())
    asyncio.run(mcp_client._allowed_tools())
    assert len(clients) == 1
    formal.setenv("TRIAGE_ENV", "test")
    formal.setenv("MCP_SERVER_URL", "http://mock-mcp:8000/mcp")
    asyncio.run(mcp_client._allowed_tools())
    assert len(clients) == 2
    formal.setenv("TRIAGE_ENV", "production")
    with pytest.raises(config.ConfigurationError):
        asyncio.run(mcp_client._allowed_tools())


def test_mock_mcp_protocol_offline_only(monkeypatch):
    monkeypatch.setenv("TRIAGE_ENV", "test")

    async def scenario():
        for module, expected in (("mock_mcp", mcp_client.ALLOWED_TOOLS),
                                  ("mock_repair_mcp", {"resources_scale"})):
            client = MultiServerMCPClient({"offline": {
                "transport": "stdio", "command": sys.executable,
                "args": ["-c", f"from kube_triage.{module} import mcp; mcp.run(transport='stdio')"],
                "env": {"TRIAGE_ENV": "test"},
            }}, handle_tool_errors=False)
            async with client.session("offline") as session:
                tools = {tool.name: tool for tool in await load_mcp_tools(session)}
                assert set(tools) == expected
                if module == "mock_mcp":
                    args = {"namespace": mcp_client.NAMESPACE}
                    for name in expected:
                        call_args = {**args, "name": "crashloop-pod"} if name in {
                            "pods_get", "pods_log"} else args
                        text = mcp_client._display_result(await tools[name].ainvoke(call_args))
                        assert '"mock": true' in text and '"source": "static-fixture"' in text
                    denied = await session.call_tool(
                        "pods_list_in_namespace", {"namespace": "default"})
                    assert denied.isError and "Namespace denied" in str(denied.content)
                else:
                    tool = tools["resources_scale"]
                    for scale, expected_replicas in ((None, 0), (1, 1), (None, 1)):
                        result = await tool.ainvoke(repair._scale_args(scale))
                        assert repair.parse_scale(result)["replicas"] == expected_replicas

    asyncio.run(scenario())


def test_init_generates_secrets_without_overwriting_existing_env(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/start.sh").write_text((ROOT / "scripts/start.sh").read_text())
    (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text())
    command = ["bash", str(tmp_path / "scripts/start.sh"), "--init-only"]
    output = subprocess.check_output(command, text=True)
    data = (tmp_path / ".env").read_text()
    values = dict(line.split("=", 1) for line in data.splitlines() if "=" in line)
    assert len(values["POSTGRES_PASSWORD"]) >= 32 and len(values["DEMO_API_TOKEN"]) >= 32
    assert values["POSTGRES_PASSWORD"] != values["DEMO_API_TOKEN"]
    assert all(values[key] not in output for key in ("POSTGRES_PASSWORD", "DEMO_API_TOKEN"))
    assert os.stat(tmp_path / ".env").st_mode & 0o777 == 0o600
    subprocess.check_call(command)
    assert (tmp_path / ".env").read_text() == data


@pytest.mark.parametrize("module", ["mock_mcp", "mock_repair_mcp"])
def test_mock_executable_refuses_production(formal, module):
    env = {**os.environ, "TRIAGE_ENV": "production"}
    result = subprocess.run([sys.executable, "-m", f"kube_triage.{module}"],
                            check=False, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and "仅允许 TRIAGE_ENV=test" in result.stderr


def test_tools_list_schema_mismatch_never_cached(formal):
    class WrongClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_tools(self, **_kwargs):
            return [type("Tool", (), {"name": "resources_scale"})()]

    formal.setenv("MCP_SERVER_URL", "http://k8s-mcp:8080/mcp")
    formal.setattr(mcp_client, "MultiServerMCPClient", WrongClient)
    formal.setattr(mcp_client, "_tools_url", None)
    formal.setattr(mcp_client, "_tools", None)
    with pytest.raises(RuntimeError, match="tools/list mismatch"):
        asyncio.run(mcp_client._allowed_tools())
    assert mcp_client._tools is None
