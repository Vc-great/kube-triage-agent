"""Static, read-only MCP fixtures. No Kubernetes code or credentials."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kube-triage-mock", host="0.0.0.0", port=8000, stateless_http=True, json_response=True)
PODS = {"crashloop-pod", "healthy-pod"}


def check_namespace(namespace: str) -> None:
    if namespace != "demo":
        raise ValueError("Namespace denied: only demo is allowed")


def check_pod(pod_name: str) -> None:
    if not pod_name or pod_name not in PODS:
        raise ValueError("Unknown or empty demo pod name")


@mcp.tool()
def list_pods(namespace: str) -> dict:
    """List two static demo Pods; never query a Kubernetes cluster."""
    check_namespace(namespace)
    return {"mock": True, "source": "static-fixture", "namespace": namespace, "pods": [
        {"name": "healthy-pod", "status": "Running"},
        {"name": "crashloop-pod", "status": "CrashLoopBackOff"},
    ]}


@mcp.tool()
def get_pod_events(namespace: str, pod_name: str) -> dict:
    """Return one static demo Event."""
    check_namespace(namespace)
    check_pod(pod_name)
    events = (["Back-off restarting failed container"] if pod_name == "crashloop-pod"
              else ["Successfully started container"])
    return {"mock": True, "source": "static-fixture", "namespace": namespace,
            "pod_name": pod_name, "events": events}


@mcp.tool()
def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 20) -> dict:
    """Return bounded static demo logs."""
    check_namespace(namespace)
    check_pod(pod_name)
    if isinstance(tail_lines, bool) or not isinstance(tail_lines, int) or not 1 <= tail_lines <= 100:
        raise ValueError("tail_lines must be an integer from 1 to 100")
    fixture = (["starting demo app", "database unavailable", "exiting with code 1"]
               if pod_name == "crashloop-pod" else ["starting demo app", "ready"])
    lines = fixture[-tail_lines:]
    output = "\n".join(lines)
    truncated = len(lines) < len(fixture)
    if len(output) > 4096:
        output, truncated = output[:4096], True
    return {"mock": True, "source": "static-fixture", "namespace": namespace,
            "pod_name": pod_name, "logs": output, "truncated": truncated}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
