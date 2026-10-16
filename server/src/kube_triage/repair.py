"""One fixed Deployment scale exercise. This module is never bound to the LLM."""

import asyncio
import base64
import json
import logging
import os
import ssl
import time
import urllib.request
from pathlib import Path

import yaml
from langchain_mcp_adapters.client import MultiServerMCPClient

from kube_triage.config import test_mode
from kube_triage.mcp_client import NAMESPACE, _display_result, _error_type, call_tool

NAME = "triage-repair-demo"
API_VERSION = "apps/v1"
KIND = "Deployment"
LABEL = "app.kubernetes.io/part-of"
PROJECT = "kube-triage-agent"
IMAGE = "busybox:1.36.1"
COMMAND = ["sh", "-c", ("mkdir -p /tmp/www && echo ready >/tmp/www/index.html && "
                         "exec httpd -f -p 8080 -h /tmp/www")]
TIMEOUT = 8
logger = logging.getLogger("kube_triage.audit")


def repair_enabled() -> bool:
    test_mode()
    return os.getenv("REPAIR_ENABLED", "false").lower() == "true"


def simulated() -> bool:
    test_mode()
    return os.getenv("REPAIR_SIMULATED", "false").lower() == "true"


def _kubeconfig() -> tuple[str, str, ssl.SSLContext]:
    """Read only the project-generated single-context JSON file; never log its contents."""
    path = Path(os.getenv("REPAIR_KUBECONFIG", "/run/kube-triage/repair-kubeconfig"))
    data = json.loads(path.read_text(encoding="utf-8"))
    if (len(data.get("clusters", [])) != 1 or len(data.get("users", [])) != 1 or
            len(data.get("contexts", [])) != 1 or
            data.get("current-context") != "kube-triage-repairer"):
        raise ValueError("Repairer kubeconfig must contain one expected context")
    cluster = data["clusters"][0]["cluster"]
    user = data["users"][0]["user"]
    context = data["contexts"][0]["context"]
    server, ca, token = (cluster.get("server"), cluster.get("certificate-authority-data"),
                         user.get("token"))
    if (not isinstance(server, str) or not server.startswith("https://") or
            not isinstance(ca, str) or not isinstance(token, str) or not token or
            cluster.get("insecure-skip-tls-verify") or context.get("namespace") != NAMESPACE or
            context.get("user") != "kube-triage-repairer"):
        raise ValueError("Repairer kubeconfig has an invalid identity or TLS configuration")
    trust = ssl.create_default_context(cadata=base64.b64decode(ca).decode("utf-8"))
    return server.rstrip("/"), token, trust


def _read_deployment_sync() -> dict:
    server, token, trust = _kubeconfig()
    url = f"{server}/apis/apps/v1/namespaces/{NAMESPACE}/deployments/{NAME}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=trust))
    with opener.open(request, timeout=TIMEOUT) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise TypeError("Deployment response is not an object")
    return data


async def read_deployment() -> dict:
    if simulated():
        scale = await read_scale()
        return {"apiVersion": API_VERSION, "kind": KIND, "metadata": {
            "name": NAME, "namespace": NAMESPACE, "uid": scale["uid"],
            "labels": {LABEL: PROJECT, "app": NAME}},
            "spec": {"replicas": scale["replicas"],
                     "selector": {"matchLabels": {"app": NAME}},
                     "template": {"metadata": {"labels": {"app": NAME}},
                                  "spec": {"automountServiceAccountToken": False,
                                           "securityContext": {"runAsNonRoot": True,
                                                               "runAsUser": 101,
                                                               "seccompProfile": {
                                                                   "type": "RuntimeDefault"}},
                                           "containers": [{"name": "web", "image": IMAGE,
                                                           "command": COMMAND,
                                                           "resources": {"requests": {
                                                               "cpu": "10m", "memory": "32Mi"},
                                                               "limits": {"cpu": "100m",
                                                                          "memory": "64Mi"}},
                                                           "securityContext": {
                                                               "allowPrivilegeEscalation": False,
                                                               "capabilities": {"drop": ["ALL"]}}}]}}}}
    return await asyncio.wait_for(asyncio.to_thread(_read_deployment_sync), TIMEOUT + 1)


def validate_deployment(data: dict, expected_uid: str | None = None) -> str:
    metadata = data.get("metadata") or {}
    labels = metadata.get("labels") or {}
    template = (data.get("spec") or {}).get("template") or {}
    template_labels = (template.get("metadata") or {}).get("labels") or {}
    spec = data.get("spec") or {}
    pod_spec = template.get("spec") or {}
    containers = pod_spec.get("containers") or []
    container = containers[0] if isinstance(containers, list) and len(containers) == 1 else {}
    security = pod_spec.get("securityContext") or {}
    container_security = container.get("securityContext") or {}
    uid = metadata.get("uid")
    if (data.get("apiVersion") != API_VERSION or data.get("kind") != KIND or
            metadata.get("namespace") != NAMESPACE or metadata.get("name") != NAME or
            labels.get(LABEL) != PROJECT or labels.get("app") != NAME or
            template_labels.get("app") != NAME or not isinstance(uid, str) or not uid or
            (spec.get("selector") or {}).get("matchLabels") != {"app": NAME} or
            pod_spec.get("automountServiceAccountToken") is not False or
            any(pod_spec.get(key) for key in ("hostNetwork", "hostPID", "hostIPC", "volumes")) or
            security.get("runAsNonRoot") is not True or security.get("runAsUser") != 101 or
            (security.get("seccompProfile") or {}).get("type") != "RuntimeDefault" or
            container.get("name") != "web" or container.get("image") != IMAGE or
            container.get("command") != COMMAND or container.get("env") or
            container.get("volumeMounts") or
            container.get("resources") != {"requests": {"cpu": "10m", "memory": "32Mi"},
                                           "limits": {"cpu": "100m", "memory": "64Mi"}} or
            container_security.get("allowPrivilegeEscalation") is not False or
            (container_security.get("capabilities") or {}).get("drop") != ["ALL"] or
            (expected_uid is not None and uid != expected_uid)):
        raise ValueError("Deployment 身份、归属标签或 UID 不符合演示资源")
    return uid


def _scale_args(scale: int | None = None) -> dict:
    args = {"apiVersion": API_VERSION, "kind": KIND, "name": NAME, "namespace": NAMESPACE}
    if scale is not None:
        if scale != 1 or isinstance(scale, bool):
            raise ValueError("Only scale=1 is allowed")
        args["scale"] = 1
    return args


async def _scale_tool():
    url = os.getenv("REPAIR_MCP_SERVER_URL", "").strip()
    expected = ("http://mock-repair-mcp:8001/mcp" if simulated() else
                "http://127.0.0.1:18081/mcp" if os.getenv("TRIAGE_ENV") == "development"
                else "http://repair-mcp:8080/mcp")
    if url != expected:
        raise ValueError("Repair MCP URL is not the project-private endpoint")
    client = MultiServerMCPClient({"repair": {"transport": "streamable_http", "url": url}},
                                  handle_tool_errors=False)
    tools = await client.get_tools(server_name="repair")
    if len(tools) != 1 or tools[0].name != "resources_scale":
        raise RuntimeError("Repair MCP tools/list must contain only resources_scale")
    return tools[0]


async def read_scale() -> dict:
    tool = await asyncio.wait_for(_scale_tool(), TIMEOUT)
    result = await asyncio.wait_for(tool.ainvoke(_scale_args()), TIMEOUT)
    return parse_scale(result)


def parse_scale(result: object) -> dict:
    data = yaml.safe_load(_display_result(result))
    if not isinstance(data, dict):
        raise TypeError("Scale response is not an object")
    metadata = data.get("metadata") or {}
    spec = data.get("spec")
    if not isinstance(spec, dict):
        raise TypeError("Scale response spec is invalid")
    replicas = spec.get("replicas")
    # Kubernetes omits the zero-valued ScaleSpec.replicas field in its YAML response.
    if not spec and (data.get("status") or {}).get("replicas") == 0:
        replicas = 0
    if (metadata.get("name") != NAME or metadata.get("namespace") != NAMESPACE or
            not isinstance(replicas, int) or isinstance(replicas, bool) or replicas < 0):
        raise ValueError("Scale response target or replicas is invalid")
    return {"replicas": replicas, "uid": metadata.get("uid")}


async def write_scale_once() -> None:
    start = time.monotonic()
    outcome = "unknown"
    try:
        tool = await asyncio.wait_for(_scale_tool(), TIMEOUT)
        result = await asyncio.wait_for(tool.ainvoke(_scale_args(1)), TIMEOUT)
        if parse_scale(result)["replicas"] != 1:
            raise ValueError("Scale update response did not reach one replica")
        outcome = "response_received"
    finally:
        logger.info(json.dumps({"event": "repair_scale_call", "namespace": NAMESPACE,
            "name": NAME, "target_replicas": 1, "outcome": outcome,
            "duration_ms": round((time.monotonic() - start) * 1000)}, ensure_ascii=False))


async def pod_readiness(thread_id: str | None) -> str:
    """Best-effort Reader lookup. An empty or ambiguous response is never Ready."""
    response = await call_tool("pods_list_in_namespace", {"namespace": NAMESPACE}, thread_id)
    if not response["ok"]:
        return "unknown (Reader MCP unavailable)"
    try:
        data = yaml.safe_load(response["result"])
        pods = data if isinstance(data, list) else data.get("items", data.get("pods", []))
        if not isinstance(pods, list):
            return "unknown (Pod list shape)"
        matched = [p for p in pods if (p.get("metadata") or {}).get("labels", {}).get("app") == NAME]
        if not matched:
            return "not ready (no matching Pod observed)"
        for pod in matched:
            conditions = (pod.get("status") or {}).get("conditions") or []
            if any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
                return "ready"
        return "not ready (matching Pod has no Ready=True condition)"
    except (TypeError, ValueError, AttributeError, yaml.YAMLError):
        return "unknown (Pod result unparseable)"


def safe_error(exc: Exception) -> str:
    kind, _message = _error_type(exc)
    return {"timeout": "调用超时", "connection": "连接中断", "forbidden": "权限不足 (403)",
            "unauthorized": "身份失效 (401)", "not_found": "目标不存在 (404)"}.get(
                kind, "查询或执行失败")
