"""Static MCP fixtures with the same four native tool names and parameters."""

from mcp.server.fastmcp import FastMCP

from kube_triage.mcp_client import NAMESPACE

mcp = FastMCP("kube-triage-mock", host="0.0.0.0", port=8000, stateless_http=True,
              json_response=True)
PODS = {"crashloop-pod", "healthy-pod"}


def check_namespace(namespace: str) -> None:
    if namespace != NAMESPACE:
        raise ValueError(f"Namespace denied: only {NAMESPACE} is allowed")


def check_pod(name: str) -> None:
    if name not in PODS:
        raise ValueError("Unknown or empty demo pod name")


@mcp.tool()
def pods_list_in_namespace(namespace: str) -> dict:
    """List two static Pods; never query Kubernetes."""
    check_namespace(namespace)
    return {"mock": True, "source": "static-fixture", "namespace": namespace, "pods": [
        {"name": "healthy-pod", "status": "Running"},
        {"name": "crashloop-pod", "status": "CrashLoopBackOff"},
    ]}


@mcp.tool()
def pods_get(namespace: str, name: str) -> dict:
    """Return a static Pod detail."""
    check_namespace(namespace)
    check_pod(name)
    return {"mock": True, "source": "static-fixture", "namespace": namespace,
            "name": name, "status": "CrashLoopBackOff" if name == "crashloop-pod" else "Running"}


@mcp.tool()
def events_list(namespace: str) -> dict:
    """Return static Events from the requested namespace."""
    check_namespace(namespace)
    return {"mock": True, "source": "static-fixture", "namespace": namespace,
            "events": ["Back-off restarting failed container", "Successfully started container"]}


@mcp.tool()
def pods_log(namespace: str, name: str, tail: int = 20) -> dict:
    """Return bounded static logs."""
    check_namespace(namespace)
    check_pod(name)
    if isinstance(tail, bool) or not isinstance(tail, int) or not 1 <= tail <= 100:
        raise ValueError("tail must be an integer from 1 to 100")
    fixture = (["starting demo app", "database unavailable", "exiting with code 1"]
               if name == "crashloop-pod" else ["starting demo app", "ready"])
    return {"mock": True, "source": "static-fixture", "namespace": namespace,
            "name": name, "logs": "\n".join(fixture[-tail:])}


# FastMCP's generated Pydantic argument models ignore extra fields by default.
# The Mock rejects them so direct MCP calls obey the same narrow contract.
for tool in mcp._tool_manager.list_tools():
    tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    tool.fn_metadata.arg_model.model_rebuild(force=True)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
