"""Read-only startup checks for the native development service."""

import asyncio
import os
import stat
import subprocess
import sys
from pathlib import Path

import psycopg
import redis
import yaml

from kube_triage import mcp_client, repair
from kube_triage.config import validate_service

ROOT = Path(__file__).resolve().parents[1]
REPAIR_CONFIG = ROOT / ".local" / "repair-kubeconfig"


def check_database():
    with psycopg.connect(host=os.environ["POSTGRES_HOST"],
                         port=int(os.environ["POSTGRES_PORT"]),
                         dbname=os.environ["POSTGRES_DB"],
                         user=os.environ["POSTGRES_USER"],
                         password=os.environ["POSTGRES_PASSWORD"],
                         connect_timeout=5) as connection:
        connection.execute("SELECT 1")


def check_redis():
    if not redis.Redis.from_url(os.environ["REDIS_URL"],
                              socket_connect_timeout=5, socket_timeout=5).ping():
        raise RuntimeError("Redis PING failed")


def _contains_mock_marker(value):
    if isinstance(value, dict):
        if value.get("mock") is True or value.get("source") == "static-fixture":
            return True
        return any(_contains_mock_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_mock_marker(item) for item in value)
    return False


async def check_reader(real):
    tools = await mcp_client._allowed_tools()
    if set(tools) != mcp_client.ALLOWED_TOOLS or len(tools) != 4:
        raise RuntimeError("Reader tool set mismatch")
    if not real:
        return
    # call_tool bounds model/UI output at 16 KiB; a real Pod list can exceed it.
    blocks = await tools["pods_list_in_namespace"].ainvoke(
        {"namespace": mcp_client.NAMESPACE})
    if (not isinstance(blocks, list) or not blocks or
            any(not isinstance(block, dict) or block.get("type") != "text" or
                not isinstance(block.get("text"), str) for block in blocks)):
        raise RuntimeError("Reader Pod list failed")
    result = yaml.safe_load("\n".join(block["text"] for block in blocks))
    if not isinstance(result, (dict, list)) or _contains_mock_marker(result):
        raise RuntimeError("Reader response is not trusted real cluster data")


def check_repair_config():
    path = Path(os.environ.get("REPAIR_KUBECONFIG", ""))
    if path != REPAIR_CONFIG or path.is_symlink() or not path.is_file():
        raise RuntimeError("Project Repairer kubeconfig missing")
    info = path.stat()
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
        raise RuntimeError("Project Repairer kubeconfig permissions invalid")
    repair._kubeconfig()  # Validate single expected identity and trusted CA without printing secrets.


def check_repair_rbac():
    minimal_env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    minimal_env["KUBECONFIG"] = str(REPAIR_CONFIG)
    for verb, resource, scale, allowed in (
        ("get", f"deployments.apps/{repair.NAME}", False, True),
        ("get", f"deployments.apps/{repair.NAME}", True, True),
        ("update", f"deployments.apps/{repair.NAME}", True, True),
        ("get", "secrets", False, False),
        ("update", "deployments.apps/other-deployment", True, False),
    ):
        command = ["kubectl", "auth", "can-i", verb, resource]
        if scale:
            command += ["--subresource=scale"]
        command += ["-n", repair.NAMESPACE]
        result = subprocess.run(command, env=minimal_env, capture_output=True, text=True,
                                timeout=10, check=False)
        if result.returncode not in (0, 1) or result.stdout.strip() != (
                "yes" if allowed else "no"):
            raise RuntimeError("Repairer RBAC check failed")


async def check_repair():
    try:
        check_repair_config()
    except Exception:  # noqa: BLE001 - credential parser may raise; never reveal content
        raise RuntimeError("Repairer kubeconfig invalid or missing") from None
    try:
        check_repair_rbac()
    except Exception:  # noqa: BLE001 - kubectl failures must not expose context data
        raise RuntimeError("Repairer RBAC unavailable or incorrect") from None
    try:
        deployment = await repair.read_deployment()
        uid = repair.validate_deployment(deployment)
    except Exception:  # noqa: BLE001 - Kubernetes API errors contain private response text
        raise RuntimeError("Repair Deployment GET or identity validation failed") from None
    try:
        scale = await repair.read_scale()  # Exact one-tool discovery and read-only Scale GET.
    except Exception:  # noqa: BLE001 - MCP transport errors contain private response text
        raise RuntimeError("Repair MCP Scale GET unavailable") from None
    if (scale["uid"] != uid or scale["replicas"] not in (0, 1) or
            (deployment.get("spec") or {}).get("replicas") != scale["replicas"]):
        raise RuntimeError("Repair target identity or replicas changed")


async def main(mode):
    checks = [("service configuration", validate_service),
              ("development database", check_database),
              ("development Redis", check_redis)]
    for label, check in checks:
        try:
            check()
        except Exception:  # noqa: BLE001 - preflight logs only the failed component
            raise RuntimeError(f"{label} unavailable") from None
    try:
        await asyncio.wait_for(check_reader(mode == "real"), timeout=20)
    except Exception:  # noqa: BLE001 - Reader data and transport details stay private
        raise RuntimeError("Reader MCP unavailable or not real") from None
    if mode == "real":
        try:
            await asyncio.wait_for(check_repair(), timeout=40)
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001 - bounded timeout and SDK errors stay private
            raise RuntimeError("Repair startup check timed out") from None


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"real", "mock", "memory-write",
                                               "memory-read", "memory", "mock-window",
                                               "mock-summary", "deep-demo"}:
        raise SystemExit("Unknown development scenario")
    try:
        asyncio.run(main(sys.argv[1]))
    except RuntimeError as exc:
        print(f"预检失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from None
