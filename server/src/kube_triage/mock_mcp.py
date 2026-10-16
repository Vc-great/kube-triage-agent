"""Four consistent synthetic Pods exposed through the native read-only MCP tools."""

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kube_triage.mcp_client import NAMESPACE

mcp = FastMCP("kube-triage-mock", host=os.getenv("MOCK_MCP_HOST", "0.0.0.0"),
              port=8000, stateless_http=True,
              json_response=True)
FIXTURES = Path(__file__).parent / "fixtures"


def load_pods() -> dict:
    dataset = os.getenv("TRIAGE_MOCK_DATASET", "phase3a")
    if dataset == "phase3a":
        paths = sorted(FIXTURES.glob("*.json"))
    elif dataset == "memory-web" and os.getenv("TRIAGE_ENV") == "test":
        paths = sorted((FIXTURES / "memory-web").glob("*.json"))
        if {path.name for path in paths} != {
                "crashloop.json", "healthy.json", "imagepull.json", "oomkilled.json"}:
            raise ValueError("Memory Web Mock fixtures missing")
    elif dataset == "issue12-blind-v1" and os.getenv("TRIAGE_ENV") == "test":
        paths = sorted((FIXTURES / "issue12").glob("*.json"))
        expected = {f"sample-{letter}.json" for letter in "abcdefgh"} | {"sample-noise.json"}
        if {path.name for path in paths} != expected:
            raise ValueError("Issue #12 Mock fixtures missing")
    else:
        raise ValueError("Unknown or non-test Mock dataset")
    pods = {}
    for path in paths:
        item = json.loads(path.read_text(encoding="utf-8"))
        if (item.get("name") in pods or not item.get("containerStatuses")
                or dataset == "memory-web" and not item.get("uid")):
            raise ValueError("Duplicate or incomplete Mock Pod")
        pods[item["name"]] = item
    return pods


PODS = load_pods()


def check_namespace(namespace: str) -> None:
    if namespace != NAMESPACE:
        raise ValueError(f"Namespace denied: only {NAMESPACE} is allowed")


def check_pod(name: str) -> None:
    if name not in PODS:
        raise ValueError("Unknown or empty demo pod name")


@mcp.tool()
def pods_list_in_namespace(namespace: str) -> dict:
    """List all synthetic Pods; never query Kubernetes."""
    check_namespace(namespace)
    return {"mock": True, "source": "static-fixture", "namespace": namespace, "pods": [
        {"name": item["name"], "phase": item["phase"]} for item in PODS.values()]}


@mcp.tool()
def pods_get(namespace: str, name: str) -> dict:
    """Return a static Pod detail."""
    check_namespace(namespace)
    check_pod(name)
    item = PODS[name]
    return {"mock": True, "source": "static-fixture", "kind": "Pod",
            "namespace": namespace, "name": name,
            "metadata": {"namespace": namespace, "name": name,
                         **({"uid": item["uid"]} if item.get("uid") else {})},
            "status": {"phase": item["phase"], "containerStatuses": item["containerStatuses"]}}


@mcp.tool()
def events_list(namespace: str) -> dict:
    """Return static Events from the requested namespace."""
    check_namespace(namespace)
    events = []
    for item in PODS.values():
        if "events" in item:
            for event in item["events"]:
                event = {**event, "involvedObject": {
                    "kind": "Pod", "name": item["name"], "namespace": namespace,
                    **({"uid": event["uid"]} if event.get("uid") else {})}}
                event.pop("uid", None)
                events.append(event)
        else:
            events.append({"involvedObject": {"kind": "Pod", "name": item["name"],
                           "namespace": namespace},
                           "type": "Normal" if item["name"] == "healthy-pod" else "Warning",
                           "reason": "Failed" if item["name"] == "imagepull-pod" else
                           "BackOff" if item["name"] != "healthy-pod" else "Started",
                           "message": item["event"]})
    return {"mock": True, "source": "static-fixture", "namespace": namespace,
            "events": events}


@mcp.tool()
def pods_log(namespace: str, name: str, tail: int = 20, container: str | None = None) -> dict:
    """Return bounded static logs."""
    check_namespace(namespace)
    check_pod(name)
    if isinstance(tail, bool) or not isinstance(tail, int) or not 1 <= tail <= 100:
        raise ValueError("tail must be an integer from 1 to 100")
    if container is not None and container != "app":
        raise ValueError("Unknown demo container")
    fixture = PODS[name]["log"]
    return {"mock": True, "source": "static-fixture", "namespace": namespace,
            "name": name, "container": container or "app", "available": fixture is not None,
            "logs": "\n".join(fixture.splitlines()[-tail:]) if fixture is not None else None,
            "reason": "container has not started" if fixture is None else None}


# FastMCP's generated Pydantic argument models ignore extra fields by default.
# The Mock rejects them so direct MCP calls obey the same narrow contract.
for tool in mcp._tool_manager.list_tools():
    tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    tool.fn_metadata.arg_model.model_rebuild(force=True)


if __name__ == "__main__":
    from kube_triage.config import test_mode

    if not test_mode():
        raise SystemExit("Mock MCP 仅允许 TRIAGE_ENV=test")
    mcp.run(transport="streamable-http")
