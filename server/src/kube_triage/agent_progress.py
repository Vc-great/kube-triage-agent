"""Small, fixed-vocabulary progress events for the ephemeral custom stream."""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from uuid import uuid4

from langgraph.config import get_config, get_stream_writer

from kube_triage.mcp_client import ALLOWED_TOOLS

audit = logging.getLogger("kube_triage.audit")
MAX_PROGRESS_EVENTS_PER_NODE = 16
_emitted: ContextVar[int] = ContextVar("agent_progress_emitted", default=0)
_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_LABELS = {
    ("context", "trim", "completed"): "历史上下文已安全裁剪",
    ("context", "trim", "failed"): "上下文预算不足，诊断未完成",
    ("context", "summary", "started"): "正在整理历史参考",
    ("context", "summary", "completed"): "历史参考已采纳",
    ("context", "summary", "cache_hit"): "沿用已校验的历史参考",
    ("context", "summary", "fallback"): "摘要失败，已回退到安全裁剪",
    ("context", "summary", "skipped"): "沿用安全裁剪，未重试失败的摘要",
    ("model", None, "started"): "正在请求模型",
    ("model", None, "completed"): "模型已返回",
    ("model", None, "failed"): "模型请求或准备失败",
    ("answer", None, "completed"): "答复已生成",
    ("tool", None, "started"): "正在执行只读工具",
    ("tool", None, "completed"): "只读工具已完成",
    ("tool", None, "failed"): "只读工具执行失败",
    ("tool", None, "skipped"): "只读工具调用已跳过",
}


def progress_event(stage: str, status: str, *, context_operation: str | None = None,
                   tool_name: str | None = None,
                   tool_call_id: str | None = None) -> dict:
    """Construct only allowlisted, bounded fields; never copy model/tool text."""
    label = _LABELS.get((stage, context_operation, status))
    if label is None:
        raise ValueError("invalid_progress_transition")
    event = {"version": 1, "type": "agent_progress", "event_id": str(uuid4()),
             "stage": stage, "status": status, "label": label}
    if context_operation is not None:
        event["context_operation"] = context_operation
    if stage == "tool":
        if isinstance(tool_name, str) and tool_name in ALLOWED_TOOLS:
            event["tool_name"] = tool_name
        if isinstance(tool_call_id, str) and _ID.fullmatch(tool_call_id):
            event["tool_call_id"] = tool_call_id
    elif tool_name is not None or tool_call_id is not None:
        raise ValueError("unexpected_progress_fields")
    return event


def emit_progress(stage: str, status: str, *, context_operation: str | None = None,
                  tool_name: str | None = None,
                  tool_call_id: str | None = None) -> None:
    """A UI transport failure cannot turn a Reader result into success/failure."""
    if _emitted.get() >= MAX_PROGRESS_EVENTS_PER_NODE:
        return
    _emitted.set(_emitted.get() + 1)
    try:
        event = progress_event(stage, status, context_operation=context_operation,
                               tool_name=tool_name, tool_call_id=tool_call_id)
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
        if isinstance(thread_id, str) and _ID.fullmatch(thread_id):
            event["thread_id"] = thread_id
        get_stream_writer()(event)
    except Exception:  # noqa: BLE001 - progress is strictly best effort
        audit.warning("agent_progress_emit_failed")


def reset_progress_budget() -> None:
    """Each graph node starts a fresh bounded emission context."""
    _emitted.set(0)
