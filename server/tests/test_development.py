"""Native development must keep the formal reader and data boundaries."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kube_triage import config, mcp_client

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("mode,url,allowed", [
    ("development", "http://127.0.0.1:18080/mcp", True),
    ("development", "http://mock-mcp:8000/mcp", False),
    ("development", "http://k8s-mcp:8080/mcp", False),
    ("development", "http://127.0.0.1:18080/mcp?redirect=mock", False),
    ("development", "http://localhost:18080/mcp", False),
    ("production", "http://127.0.0.1:18080/mcp", False),
    ("production", "http://k8s-mcp:8080/mcp", True),
])
def test_reader_endpoint_by_environment(monkeypatch, mode, url, allowed):
    monkeypatch.setenv("TRIAGE_ENV", mode)
    monkeypatch.setenv("REPAIR_SIMULATED", "false")
    monkeypatch.setenv("MCP_SERVER_URL", url)
    if allowed:
        assert config.reader_url() == url
    else:
        with pytest.raises(config.ConfigurationError):
            config.reader_url()


def test_development_requires_real_model_and_rejects_simulation(monkeypatch):
    monkeypatch.setenv("TRIAGE_ENV", "development")
    monkeypatch.setenv("REPAIR_SIMULATED", "true")
    with pytest.raises(config.ConfigurationError):
        config.test_mode()
    monkeypatch.setenv("REPAIR_SIMULATED", "false")
    monkeypatch.setenv("LLM_ENABLED", "false")
    with pytest.raises(config.ConfigurationError):
        config.validate_llm()


def test_switching_to_development_rebuilds_reader_cache(monkeypatch):
    urls = []

    class Client:
        def __init__(self, connections, **kwargs):
            urls.append(connections["kubernetes"]["url"])

        async def get_tools(self, **kwargs):
            return [SimpleNamespace(name=name) for name in mcp_client.ALLOWED_TOOLS]

    monkeypatch.setattr(mcp_client, "MultiServerMCPClient", Client)
    monkeypatch.setattr(mcp_client, "_tools_url", None)
    monkeypatch.setattr(mcp_client, "_tools", None)
    monkeypatch.setattr(mcp_client, "_client", None)
    monkeypatch.setenv("REPAIR_SIMULATED", "false")
    for mode, url in [("production", "http://k8s-mcp:8080/mcp"),
                      ("development", "http://127.0.0.1:18080/mcp")]:
        monkeypatch.setenv("TRIAGE_ENV", mode)
        monkeypatch.setenv("MCP_SERVER_URL", url)
        assert len(asyncio.run(mcp_client._allowed_tools())) == 4
    assert urls == ["http://k8s-mcp:8080/mcp", "http://127.0.0.1:18080/mcp"]


def test_dev_stop_rejects_reused_pid(monkeypatch):
    spec = importlib.util.spec_from_file_location("dev", ROOT / "scripts/dev.py")
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    monkeypatch.setattr(dev.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(stdout="python /someone-elses/script.py"))
    assert not dev.alive({"pid": 123, "token": "owned"})


def test_cors_supports_remote_and_native_web():
    origins = json.loads((ROOT / "server/aegra.json").read_text())["http"]["cors"]["allow_origins"]
    assert {"http://192.168.31.110:13000", "http://localhost:13000",
            "http://127.0.0.1:13000"} <= set(origins)
