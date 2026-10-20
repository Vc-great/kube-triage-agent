"""Native development startup must prove the real read boundaries."""

import asyncio
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kube_triage import mcp_client, repair

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("dev_preflight", ROOT / "scripts/dev_preflight.py")
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


@pytest.mark.parametrize("blocks,passes", [
    ([{"type": "text", "text": "items: []"}], True),
    ([{"type": "text", "text": "mock: true\nsource: static-fixture"}], False),
    ([{"type": "error", "text": "unavailable"}], False),
    ([{"type": "text", "text": "invalid scalar"}], False),
])
def test_real_reader_requires_actual_non_mock_read(monkeypatch, blocks, passes):
    class PodList:
        async def ainvoke(self, args):
            assert args == {"namespace": mcp_client.NAMESPACE}
            return blocks

    async def tools():
        return {name: PodList() for name in mcp_client.ALLOWED_TOOLS}

    monkeypatch.setattr(mcp_client, "_allowed_tools", tools)
    if passes:
        asyncio.run(PREFLIGHT.check_reader(True))
    else:
        with pytest.raises(RuntimeError):
            asyncio.run(PREFLIGHT.check_reader(True))


def test_real_reader_preflight_uses_complete_result(monkeypatch):
    class PodList:
        async def ainvoke(self, _args):
            return [{"type": "text", "text": "items:\n" +
                     "  - name: real-pod\n" * 1200}]

    async def tools():
        return {name: PodList() for name in mcp_client.ALLOWED_TOOLS}

    monkeypatch.setattr(mcp_client, "_allowed_tools", tools)
    asyncio.run(PREFLIGHT.check_reader(True))


def test_reader_service_unavailable_fails_preflight(monkeypatch):
    async def unavailable():
        raise ConnectionError("private transport detail")

    monkeypatch.setattr(mcp_client, "_allowed_tools", unavailable)
    with pytest.raises(ConnectionError):
        asyncio.run(PREFLIGHT.check_reader(True))


def test_repair_rbac_checks_only_authorization(monkeypatch):
    commands = []

    def run(command, **kwargs):
        assert kwargs["env"]["KUBECONFIG"] == str(PREFLIGHT.REPAIR_CONFIG)
        commands.append(command)
        allowed = "secrets" not in command and "other-deployment" not in " ".join(command)
        return SimpleNamespace(returncode=0 if allowed else 1,
                               stdout="yes\n" if allowed else "no\n")

    monkeypatch.setattr(subprocess, "run", run)
    PREFLIGHT.check_repair_rbac()
    assert len(commands) == 5
    assert all(command[:3] == ["kubectl", "auth", "can-i"] for command in commands)
    assert sum("--subresource=scale" in command for command in commands) == 3


@pytest.mark.parametrize("scale_uid,replicas,accepted", [
    ("expected-uid", 0, True),
    ("expected-uid", 1, True),
    ("different-uid", 1, False),
    ("expected-uid", 2, False),
])
def test_repair_preflight_accepts_zero_or_one_only(monkeypatch, scale_uid, replicas, accepted):
    deployment = yaml.safe_load((ROOT / "infra/k8s/repair-demo.yaml").read_text())
    deployment["metadata"]["uid"] = "expected-uid"
    deployment["spec"]["replicas"] = replicas
    monkeypatch.setattr(PREFLIGHT, "check_repair_config", lambda: None)
    monkeypatch.setattr(PREFLIGHT, "check_repair_rbac", lambda: None)

    async def read_deployment():
        return deployment

    async def read_scale():
        return {"uid": scale_uid, "replicas": replicas}

    monkeypatch.setattr(repair, "read_deployment", read_deployment)
    monkeypatch.setattr(repair, "read_scale", read_scale)
    if accepted:
        asyncio.run(PREFLIGHT.check_repair())
    else:
        with pytest.raises(RuntimeError, match="identity or replicas"):
            asyncio.run(PREFLIGHT.check_repair())


def test_repair_mcp_service_unavailable_fails_preflight(monkeypatch):
    deployment = yaml.safe_load((ROOT / "infra/k8s/repair-demo.yaml").read_text())
    deployment["metadata"]["uid"] = "expected-uid"
    monkeypatch.setattr(PREFLIGHT, "check_repair_config", lambda: None)
    monkeypatch.setattr(PREFLIGHT, "check_repair_rbac", lambda: None)

    async def read_deployment():
        return deployment

    async def unavailable():
        raise ConnectionError("private transport detail")

    monkeypatch.setattr(repair, "read_deployment", read_deployment)
    monkeypatch.setattr(repair, "read_scale", unavailable)
    with pytest.raises(RuntimeError, match="Repair MCP Scale GET unavailable"):
        asyncio.run(PREFLIGHT.check_repair())


def test_repair_config_requires_private_project_file(tmp_path, monkeypatch):
    path = tmp_path / "repair-kubeconfig"
    path.write_text("synthetic")
    path.chmod(0o644)
    monkeypatch.setattr(PREFLIGHT, "REPAIR_CONFIG", path)
    monkeypatch.setenv("REPAIR_KUBECONFIG", str(path))
    with pytest.raises(RuntimeError, match="permissions"):
        PREFLIGHT.check_repair_config()


@pytest.mark.parametrize("environment,url,accepted", [
    ("development", "http://127.0.0.1:18081/mcp", True),
    ("development", "http://repair-mcp:8080/mcp", False),
    ("production", "http://127.0.0.1:18081/mcp", False),
    ("production", "http://repair-mcp:8080/mcp", True),
    ("test", "http://127.0.0.1:18081/mcp", False),
])
def test_repair_url_is_bound_to_its_environment(monkeypatch, environment, url, accepted):
    monkeypatch.setenv("TRIAGE_ENV", environment)
    monkeypatch.setenv("REPAIR_SIMULATED", "false")
    monkeypatch.setenv("REPAIR_MCP_SERVER_URL", url)

    class Client:
        def __init__(self, connections, **_kwargs):
            assert connections["repair"]["url"] == url

        async def get_tools(self, **_kwargs):
            return [SimpleNamespace(name="resources_scale")]

    monkeypatch.setattr(repair, "MultiServerMCPClient", Client)
    if accepted:
        assert asyncio.run(repair._scale_tool()).name == "resources_scale"
    else:
        with pytest.raises(ValueError, match="project-private endpoint"):
            asyncio.run(repair._scale_tool())
