"""Opt-in process-local scale simulator. Never contacts Kubernetes."""

from mcp.server.fastmcp import FastMCP

from kube_triage.repair import API_VERSION, KIND, NAME, NAMESPACE

mcp = FastMCP("kube-triage-repair-simulated", host="0.0.0.0", port=8001,
              stateless_http=True, json_response=True)
replicas = 0


@mcp.tool()
def resources_scale(apiVersion: str, kind: str, name: str,
                    namespace: str, scale: int | None = None) -> str:
    """Simulated fixed-target scale lookup or change for offline Aegra tests."""
    global replicas
    if (apiVersion, kind, name, namespace) != (API_VERSION, KIND, NAME, NAMESPACE):
        raise ValueError("Only the fixed simulated Deployment is available")
    if scale is not None:
        if isinstance(scale, bool) or scale != 1:
            raise ValueError("Only simulated scale=1 is allowed")
        replicas = 1
    return ("# simulated=true; no Kubernetes API request\n"
            "apiVersion: autoscaling/v1\nkind: Scale\nmetadata:\n"
            f"  name: {NAME}\n  namespace: {NAMESPACE}\n  uid: simulated-demo-uid\n"
            f"spec:\n  replicas: {replicas}\nstatus:\n  replicas: {replicas}\n")


for tool in mcp._tool_manager.list_tools():
    tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    tool.fn_metadata.arg_model.model_rebuild(force=True)


if __name__ == "__main__":
    from kube_triage.config import test_mode

    if not test_mode():
        raise SystemExit("Mock MCP 仅允许 TRIAGE_ENV=test")
    mcp.run(transport="streamable-http")
