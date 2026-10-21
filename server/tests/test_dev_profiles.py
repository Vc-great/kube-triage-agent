"""Native developer scenario boundaries without starting external services."""

import importlib.util
import io
import json
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


@pytest.fixture(autouse=True)
def isolated_env_file(tmp_path, monkeypatch):
    """Profile checks must never depend on developer or CI private configuration."""
    path = tmp_path / "dev.env"
    path.write_text("# Synthetic profile fixture without Langfuse credentials.\n")
    path.chmod(0o600)
    monkeypatch.setattr(DEV, "ENV_FILE", path)


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
    assert envs["api"]["OTEL_TARGETS"] == ""
    assert not any(key.startswith("LANGFUSE_") for env in envs.values() for key in env)
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


def test_deep_demo_never_loads_trace_or_inherits_provider_overrides(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("deep-demo must not read Langfuse credentials")

    monkeypatch.setattr(DEV, "read_langfuse_env", forbidden)
    host = {"PATH": "/usr/bin", "LANGFUSE_SECRET_KEY": "synthetic-trace-key",
            "LANGSMITH_TRACING": "true", "LANGCHAIN_API_KEY": "synthetic-trace-key",
            "OTEL_TARGETS": "LANGFUSE", "EVAL_LUNA_RESPONSES_HIGH": "true",
            "DEEP_DIAGNOSIS_FAKE_MODEL": "true", "MCP_SERVER_URL": "http://real.invalid",
            "HTTP_PROXY": "http://unapproved.invalid", "LLM_MODEL": "unapproved"}
    values = {**VALUES, "LLM_BASE_URL": "http://192.168.31.110:8317/v1"}
    envs = DEV.child_environments("deep-demo", values, host)
    api = envs["api"]
    assert api["TRIAGE_ENV"] == "test"
    assert api["EVAL_LUNA_RESPONSES_HIGH"] == "false"
    assert api["DEEP_DIAGNOSIS_ENABLE_PROVIDER"] == "true"
    assert api["DEEP_DIAGNOSIS_FAKE_MODEL"] == "false"
    assert api["AEGRA_CONFIG"] == "aegra.phase-b1.json"
    assert api["MCP_SERVER_URL"] == "http://127.0.0.1:8000/mcp"
    assert api["OTEL_TARGETS"] == ""
    assert api["OTEL_SDK_DISABLED"] == "true"
    assert api["WORKER_QUEUE_KEY"].startswith("deep-demo:")
    assert api["REDIS_CHANNEL_PREFIX"].startswith("deep-demo:")
    assert api["WORKER_QUEUE_KEY"] != "aegra:jobs"
    assert api["REDIS_CHANNEL_PREFIX"] != "aegra:run:"
    assert api["BG_JOB_TIMEOUT_SECS"] == "120"
    assert api["BG_JOB_MAX_RETRIES"] == "0"
    assert api["LANGSMITH_TRACING"] == api["LANGCHAIN_TRACING_V2"] == "false"
    assert not any(key.startswith("LANGFUSE_") or key.endswith("PROXY") for key in api)
    for key in ("REPAIR_ENABLED", "INCIDENT_MEMORY_ENABLED", "CONTEXT_WINDOW_ENABLED",
                "CONTEXT_SUMMARY_ENABLED"):
        assert api[key] == "false"
    assert envs["web"]["NEXT_PUBLIC_ASSISTANT_ID"] == "deep_diagnosis_planning"
    assert envs["web"]["NEXT_PUBLIC_DEEP_DEMO"] == "true"
    assert envs["mock"]["TRIAGE_MOCK_DATASET"] == "memory-web"
    assert DEV.profile_summary("deep-demo")["model"] == "real"
    assert DEV.required_ports("deep-demo") == DEV.required_ports("mock")
    for name in ("web", "mock", "tunnel"):
        assert not (set(envs[name]) & DEV.PRIVATE_KEYS)


@pytest.mark.parametrize("field,value", [
    ("LLM_MODEL", "gpt-other"),
    ("LLM_BASE_URL", "https://unapproved.invalid/v1"),
    ("LLM_BASE_URL", "http://192.168.31.110:8317/v1?redirect=1"),
    ("LLM_BASE_URL", ""),
])
def test_deep_demo_refuses_unapproved_provider(field, value):
    values = {**VALUES, "LLM_BASE_URL": "http://192.168.31.110:8317/v1", field: value}
    with pytest.raises(RuntimeError, match="仅允许已批准 CPA"):
        DEV.child_environments("deep-demo", values)


def test_deep_demo_model_uses_chat_completions(monkeypatch):
    from kube_triage import llm

    envs = DEV.child_environments("deep-demo", {
        **VALUES, "LLM_BASE_URL": "http://192.168.31.110:8317/v1"})
    monkeypatch.setattr(os, "environ", envs["api"])
    model = llm.chat_model()
    assert model.model_name == "gpt-6-luna"
    assert not model._use_responses_api({"messages": []})


@pytest.mark.parametrize("name", ["server/.env", "apps/web/.env.local",
                                 "apps/web/.env.development"])
def test_deep_demo_rejects_secondary_dotenv(tmp_path, monkeypatch, name):
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("LANGSMITH_TRACING=true\n")
    monkeypatch.setattr(DEV, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="拒绝 server/Web 本地 dotenv"):
        DEV.validate_demo_files()


@pytest.mark.parametrize("graphs,ready", [
    (["deep_diagnosis", "deep_diagnosis_planning", "agent"], True),
    (["deep_diagnosis"], False),
])
def test_deep_demo_readiness_requires_both_graphs(monkeypatch, graphs, ready):
    response = io.BytesIO(json.dumps([{"graph_id": graph} for graph in graphs]).encode())
    response.status = 200
    monkeypatch.setattr(DEV.urllib.request, "urlopen", lambda *_args, **_kwargs: response)
    assert DEV.api_ready({"DEMO_API_TOKEN": "synthetic", "AEGRA_CONFIG": "aegra.phase-b1.json"}) is ready
