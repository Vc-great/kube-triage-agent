"""Allowlisted adapter calls, finite timeout, and metadata-only audit events."""

import asyncio
import json
import logging
import os
import re
import time

from langchain_mcp_adapters.client import MultiServerMCPClient

ALLOWED_TOOLS = frozenset({"list_pods", "get_pod_events", "get_pod_logs"})
POD_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
MCP_TIMEOUT_SECONDS = 8
logger = logging.getLogger("kube_triage.audit")
_client = MultiServerMCPClient({"mock": {
    "transport": "streamable_http",
    "url": os.environ.get("MCP_SERVER_URL", "http://mock-mcp:8000/mcp"),
}}, handle_tool_errors=False)
_tools = None


def validate_call(name: str, arguments: dict) -> None:
    if name not in ALLOWED_TOOLS:
        raise ValueError("Tool denied: not on the read-only allowlist")
    if arguments.get("namespace") != "demo":
        raise ValueError("Namespace denied: only demo is allowed")
    if name != "list_pods":
        pod_name = arguments.get("pod_name")
        if not isinstance(pod_name, str) or not POD_NAME.fullmatch(pod_name):
            raise ValueError("pod_name must be a non-empty Kubernetes-style name")
    if name == "get_pod_logs":
        tail_lines = arguments.get("tail_lines", 20)
        if isinstance(tail_lines, bool) or not isinstance(tail_lines, int) or not 1 <= tail_lines <= 100:
            raise ValueError("tail_lines must be an integer from 1 to 100")


async def _allowed_tools() -> dict:
    global _tools
    if _tools is None:
        discovered = await _client.get_tools(server_name="mock")
        _tools = {tool.name: tool for tool in discovered if tool.name in ALLOWED_TOOLS}
        if set(_tools) != ALLOWED_TOOLS:
            _tools = None
            raise RuntimeError("Mock MCP tools differ from the allowlist")
    return _tools


def _error_type(exc: Exception) -> tuple[str, str]:
    nested = [exc]
    if isinstance(exc, BaseExceptionGroup):
        nested.extend(exc.exceptions)
    if exc.__cause__ is not None:
        nested.append(exc.__cause__)
    if any(isinstance(item, (TimeoutError, asyncio.TimeoutError)) or
           "Timeout" in type(item).__name__ for item in nested):
        return "timeout", "Mock MCP 调用超时，请稍后重试。"
    if any(isinstance(item, (ConnectionError, OSError)) or
           "ConnectError" in type(item).__name__ for item in nested):
        return "connection", "Mock MCP 服务暂时不可用。"
    if any(type(item).__name__ in {"ToolException", "_MCPToolExecutionError"} for item in nested):
        return "tool_rejected", "Mock MCP 工具拒绝了参数。"
    return "server_error", "Mock MCP 调用失败，请查看服务日志。"


def normalize_result(result: object) -> object:
    """Unwrap the adapter's single MCP text block into its JSON fixture."""
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        block = result[0]
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            try:
                return json.loads(block["text"])
            except ValueError:
                pass
    return result


async def call_tool(name: str, arguments: dict, thread_id: str | None = None) -> dict:
    start = time.monotonic()
    outcome, error_type = "success", None
    try:
        validate_call(name, arguments)
        tools = await asyncio.wait_for(_allowed_tools(), MCP_TIMEOUT_SECONDS)
        result = await asyncio.wait_for(tools[name].ainvoke(arguments), MCP_TIMEOUT_SECONDS)
        return {"ok": True, "result": normalize_result(result)}
    except ValueError as exc:
        outcome, error_type = "rejected", "policy"
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - MCP transport can raise nested SDK errors
        error_type, message = _error_type(exc)
        outcome = "failed"
        return {"ok": False, "error": message, "error_type": error_type}
    finally:
        logger.info(json.dumps({"event": "mcp_tool_call", "thread_id": thread_id,
            "tool_name": name, "namespace": "demo" if arguments.get("namespace") == "demo" else "<denied>",
            "duration_ms": round((time.monotonic() - start) * 1000),
            "outcome": outcome, "error_type": error_type}, ensure_ascii=False))
