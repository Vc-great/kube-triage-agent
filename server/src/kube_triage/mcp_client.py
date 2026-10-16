"""Call the four native, read-only Kubernetes MCP tools."""

import asyncio
import json
import logging
import re
import time
import traceback
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from kube_triage.config import ConfigurationError, reader_url

NAMESPACE = "kube-triage-demo"
ALLOWED_TOOLS = frozenset({"pods_list_in_namespace", "pods_get", "events_list", "pods_log"})
TOOL_ARGUMENTS = {
    "pods_list_in_namespace": (("namespace",), ()),
    "pods_get": (("namespace", "name"), ()),
    "events_list": (("namespace",), ()),
    "pods_log": (("namespace", "name"), ("tail", "container")),
}
TOOL_DESCRIPTIONS = {
    "pods_list_in_namespace": "列出目标 Namespace 中的 Pod。",
    "pods_get": "读取目标 Namespace 中指定 Pod 的详情。",
    "events_list": "列出目标 Namespace 中的 Event。",
    "pods_log": "读取目标 Namespace 中指定 Pod 的容器日志。",
}
POD_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
MCP_TIMEOUT_SECONDS = 8
MAX_RESULT_CHARS = 16 * 1024
logger = logging.getLogger("kube_triage.audit")
_client = None
_tools = None
_tools_url = None

def validate_call(name: str, arguments: dict) -> None:
    if not isinstance(arguments, dict):
        raise TypeError("Tool parameters must be an object")
    if name not in ALLOWED_TOOLS:
        raise ValueError("Tool denied: not on the read-only allowlist")
    required_names, optional_names = TOOL_ARGUMENTS[name]
    required = set(required_names)
    if arguments.get("namespace") != NAMESPACE:
        raise ValueError(f"Namespace denied: only {NAMESPACE} is allowed")
    if "name" in required:
        pod = arguments.get("name")
        if not isinstance(pod, str) or len(pod) > 253 or not POD_NAME.fullmatch(pod):
            raise ValueError("name must be a Kubernetes-style Pod name")
    allowed = required | set(optional_names)
    if name == "pods_log":
        tail = arguments.get("tail", 20)
        if isinstance(tail, bool) or not isinstance(tail, int) or not 1 <= tail <= 100:
            raise ValueError("tail must be an integer from 1 to 100")
        if "container" in arguments:
            container = arguments["container"]
            if (not isinstance(container, str) or len(container) > 253 or
                    not POD_NAME.fullmatch(container)):
                raise ValueError("container must be a Kubernetes-style name")
    if not required <= set(arguments) or not set(arguments) <= allowed:
        raise ValueError("Unexpected or missing tool parameters")


def build_model_tool_schemas(native_tools: dict) -> list[dict]:
    """Expose only the arguments accepted by validate_call; execution stays native MCP."""
    if set(native_tools) != ALLOWED_TOOLS or len(native_tools) != len(ALLOWED_TOOLS):
        raise RuntimeError("MCP tools/list mismatch: expected four tools")
    fields = {
        "namespace": {"type": "string", "enum": [NAMESPACE],
                      "description": "固定目标 Namespace。"},
        "name": {"type": "string", "pattern": POD_NAME.pattern, "maxLength": 253,
                 "description": "Pod 名称。"},
        "tail": {"type": "integer", "minimum": 1, "maximum": 100,
                 "description": "返回的末尾日志行数；省略时默认 20。"},
        "container": {"type": "string", "pattern": POD_NAME.pattern, "maxLength": 253,
                      "description": "容器名称。"},
    }
    schemas = []
    for name, (required, optional) in TOOL_ARGUMENTS.items():
        schemas.append({"type": "function", "function": {
            "name": name, "description": TOOL_DESCRIPTIONS[name],
            "parameters": {"type": "object",
                           "properties": {key: fields[key] for key in (*required, *optional)},
                           "required": list(required), "additionalProperties": False},
        }})
    return schemas


async def _allowed_tools() -> dict:
    global _client, _tools, _tools_url
    url = reader_url()  # Validate even after discovering tools under a previous configuration.
    if _tools_url != url:
        _tools = None
        _client = MultiServerMCPClient({"kubernetes": {
            "transport": "streamable_http", "url": url,
        }}, handle_tool_errors=False)
        _tools_url = url
    if _tools is None:
        discovered = await _client.get_tools(server_name="kubernetes")
        names = {tool.name for tool in discovered}
        if names != ALLOWED_TOOLS or len(discovered) != 4:
            raise RuntimeError(f"MCP tools/list mismatch: expected four tools, got {len(names)}")
        _tools = {tool.name: tool for tool in discovered}
    return _tools


def _error_type(exc: Exception) -> tuple[str, str]:
    nested = [exc]
    if isinstance(exc, BaseExceptionGroup):
        nested.extend(exc.exceptions)
    if exc.__cause__ is not None:
        nested.append(exc.__cause__)
    detail = " ".join(str(item).lower() for item in nested)
    if any(isinstance(item, (TimeoutError, asyncio.TimeoutError)) or
           "Timeout" in type(item).__name__ for item in nested):
        return "timeout", "Kubernetes MCP 调用超时，请重试。"
    if any(isinstance(item, (ConnectionError, OSError)) or
           "ConnectError" in type(item).__name__ for item in nested):
        return "connection", "Kubernetes MCP 连接失败，请检查本项目服务。"
    if "forbidden" in detail or " 403" in detail:
        return "forbidden", "Kubernetes 拒绝访问（403）：请检查受限 ServiceAccount 的 RBAC。"
    if "unauthorized" in detail or " 401" in detail or "token expired" in detail:
        return "unauthorized", "Kubernetes 身份认证失败（401），短期 Token 可能已过期。"
    if "not found" in detail or " 404" in detail:
        return "not_found", "Kubernetes 对象不存在（404）。"
    if any(type(item).__name__ in {"ToolException", "_MCPToolExecutionError"} for item in nested):
        return "tool_rejected", "Kubernetes MCP 工具执行失败；请检查参数或服务日志。"
    return "server_error", "Kubernetes MCP 调用失败；请检查服务日志。"


def _display_result(result: object) -> str:
    """Keep native MCP content as text; bound what enters the checkpoint and UI."""
    if isinstance(result, list):
        parts = [block.get("text", str(block)) if isinstance(block, dict) else str(block)
                 for block in result]
        content = "\n".join(parts)
    elif isinstance(result, str):
        content = result
    else:
        content = json.dumps(result, ensure_ascii=False)
    return content[:MAX_RESULT_CHARS] + ("\n[结果已截断]" if len(content) > MAX_RESULT_CHARS else "")


async def call_tool(name: str, arguments: dict, thread_id: str | None = None) -> dict:
    start = time.monotonic()
    outcome, error_type = "success", None
    try:
        try:
            validate_call(name, arguments)
        except (TypeError, ValueError):
            outcome, error_type = "rejected", "policy"
            return {"ok": False, "error": "工具名称或参数不符合只读策略。",
                    "error_type": error_type}
        tools = await asyncio.wait_for(_allowed_tools(), MCP_TIMEOUT_SECONDS)
        safe_args = {**arguments, "tail": arguments.get("tail", 20)} if name == "pods_log" else arguments
        result = await asyncio.wait_for(tools[name].ainvoke(safe_args), MCP_TIMEOUT_SECONDS)
        return {"ok": True, "result": _display_result(result)}
    except ConfigurationError:
        outcome, error_type = "failed", "configuration"
        raise
    except Exception as exc:  # noqa: BLE001 - SDK raises transport and tool errors
        error_type, message = _error_type(exc)
        outcome = "failed"
        frames = traceback.extract_tb(exc.__traceback__)[-4:]
        logger.warning(json.dumps({"event": "mcp_tool_failure",
            "exception_type": type(exc).__name__,
            "nested_types": ([type(item).__name__ for item in exc.exceptions]
                             if isinstance(exc, BaseExceptionGroup) else []),
            "frames": [{"file": Path(frame.filename).name, "line": frame.lineno,
                        "function": frame.name} for frame in frames]}, ensure_ascii=False))
        return {"ok": False, "error": message, "error_type": error_type}
    finally:
        logger.info(json.dumps({"event": "mcp_tool_call", "thread_id": thread_id,
            "tool_name": name if name in ALLOWED_TOOLS else "<denied>",
            "namespace": NAMESPACE if isinstance(arguments, dict) and
            arguments.get("namespace") == NAMESPACE
            else "<denied>", "duration_ms": round((time.monotonic() - start) * 1000),
            "outcome": outcome, "error_type": error_type}, ensure_ascii=False))
