"""Native developer scenario boundaries without starting external services."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from kube_triage.config import validate_service

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("native_dev", ROOT / "scripts/dev.py")
DEV = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEV)
VALUES = {"POSTGRES_PASSWORD": "synthetic-db-secret",
          "DEMO_API_TOKEN": "synthetic-demo-secret",
          "LLM_MODEL": "gpt-6-luna", "LLM_BASE_URL": "https://example.invalid/v1",
          "LLM_API_KEY": "synthetic-model-secret",
          "INCIDENT_MEMORY_PROVENANCE_SECRET": "independent-synthetic-memory-secret-12345"}


@pytest.mark.parametrize("mode,reader,memory,context,port,repair", [
    ("real", "real", "read-write", "summary", 18081, "real"),
    ("mock", "mock", "off", "off", 8000, "off"),
    ("memory-write", "mock", "write", "off", 8000, "off"),
    ("memory-read", "mock", "read", "off", 8000, "off"),
    ("memory", "mock", "read-write", "off", 8000, "off"),
    ("mock-window", "mock", "off", "window", 8000, "off"),
    ("mock-summary", "mock", "off", "summary", 8000, "off"),
])
def test_profile_preflight(monkeypatch, mode, reader, memory, context, port, repair):
    host = {"PATH": "/usr/bin", "HOME": "/tmp", "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "LLM_API_KEY": "inherited-secret", "DEMO_API_TOKEN": "inherited-token",
            "CONTEXT_SUMMARY_ENABLED": "true", "NEXT_PUBLIC_API_URL": "wrong"}
    envs = DEV.child_environments(mode, VALUES, host)
    assert DEV.profile_summary(mode) == {"reader": reader, "memory": memory,
                                         "context": context, "repair": repair}
    assert DEV.required_ports(mode)[-1] == port
    assert envs["api"]["REPAIR_ENABLED"] == ("true" if mode == "real" else "false")
    assert envs["api"]["REPAIR_SIMULATED"] == "false"
    assert envs["api"]["POSTGRES_DB"] == envs["api"]["POSTGRES_USER"] == (
        "kube_triage_agent_dev")
    assert "LLM_API_KEY" not in envs["web"]
    assert "DEMO_API_TOKEN" not in envs["web"]
    assert "CONTEXT_SUMMARY_ENABLED" not in envs["web"]
    assert envs["api"]["DEMO_API_TOKEN"] == VALUES["DEMO_API_TOKEN"]
    if reader == "mock":
        assert envs["mock"]["TRIAGE_MOCK_DATASET"] == "memory-web"
        assert envs["mock"]["MOCK_MCP_HOST"] == "127.0.0.1"
        assert "LLM_API_KEY" not in envs["mock"]
        assert "POSTGRES_PASSWORD" not in envs["mock"]
        assert envs["api"]["EVAL_LUNA_RESPONSES_HIGH"] == "true"
    else:
        assert "mock" not in envs
        assert 18080 in DEV.required_ports(mode)
        assert envs["api"]["REPAIR_MCP_SERVER_URL"] == "http://127.0.0.1:18081/mcp"
        assert envs["api"]["REPAIR_KUBECONFIG"] == str(DEV.ROOT / ".local/repair-kubeconfig")
    assert ("INCIDENT_MEMORY_PROVENANCE_SECRET" in envs["api"]) == (memory != "off")
    assert envs["api"]["CONTEXT_ESTIMATED_TOTAL_BUDGET"] == (
        "6500" if context != "off" else "16384")
    monkeypatch.setattr(os, "environ", envs["api"])
    validate_service()


def test_web_environment_never_receives_private_values():
    envs = DEV.child_environments("web", VALUES, {"PATH": "/usr/bin",
                                                   "LLM_API_KEY": "inherited-secret"})
    assert set(envs) == {"web"}
    assert envs["web"]["NEXT_PUBLIC_API_URL"] == "http://192.168.31.110:12026"
    assert not (set(envs["web"]) & DEV.PRIVATE_KEYS)
    assert DEV.required_ports("web") == (13000,)


@pytest.mark.parametrize("content,error", [
    ("DEMO_API_TOKEN=one\nDEMO_API_TOKEN=two\n", "重复"),
    ("TRIAGE_ENV=test\n", "不允许"),
    ("not-an-assignment\n", "格式错误"),
])
def test_private_file_rejects_ambiguous_configuration(tmp_path, monkeypatch, content, error):
    path = tmp_path / "dev.env"
    path.write_text(content)
    path.chmod(0o600)
    monkeypatch.setattr(DEV, "ENV_FILE", path)
    with pytest.raises(RuntimeError, match=error):
        DEV.read_env()


def test_private_file_requires_owner_only_permissions(tmp_path, monkeypatch):
    path = tmp_path / "dev.env"
    path.write_text("DEMO_API_TOKEN=synthetic\n")
    path.chmod(0o644)
    monkeypatch.setattr(DEV, "ENV_FILE", path)
    with pytest.raises(RuntimeError, match="chmod 600"):
        DEV.read_env()


def test_start_requires_explicit_stop_for_existing_supervisor(tmp_path, monkeypatch):
    monkeypatch.setattr(DEV, "DIRECTORY", tmp_path / "dev")
    monkeypatch.setattr(DEV, "state_read", lambda: {"pid": 123, "token": "owned"})
    monkeypatch.setattr(DEV, "alive", lambda _state: True)
    monkeypatch.setattr(sys, "argv", ["dev.py", "start", "mock"])
    with pytest.raises(RuntimeError, match="先执行 make dev-stop"):
        DEV.main()
