"""Deterministic demo graph: real MCP transport, static data, no LLM or Kubernetes."""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from kube_triage.mcp_client import call_tool


def _last_user_text(state: MessagesState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            if isinstance(message.content, str):
                return message.content
            if isinstance(message.content, list):
                return " ".join(
                    part if isinstance(part, str) else str(part.get("text", ""))
                    for part in message.content
                    if isinstance(part, (str, dict))
                )
            return str(message.content)
    return ""


def parse_demo_command(text: str) -> tuple[str, dict] | None:
    parts = text.strip().lower().split()
    if not parts or parts[0] not in {"pods", "events", "logs"}:
        return None
    if parts[0] == "pods" and len(parts) == 2:
        return "list_pods", {"namespace": parts[1]}
    if parts[0] in {"events", "logs"} and len(parts) == 3:
        name = "get_pod_events" if parts[0] == "events" else "get_pod_logs"
        args = {"namespace": parts[1], "pod_name": parts[2]}
        if name == "get_pod_logs":
            args["tail_lines"] = 20
        return name, args
    return "invalid_command", {"namespace": parts[1] if len(parts) > 1 else ""}


def _route(state: MessagesState) -> Literal["tool_request", "approval_prompt", "echo"]:
    text = _last_user_text(state).strip().lower()
    if text.startswith("/approve-demo"):
        return "approval_prompt"
    if parse_demo_command(text):
        return "tool_request"
    return "echo"


def _echo(state: MessagesState) -> dict:
    return {"messages": [AIMessage(content=(
        "这是 Mock 演示。试试 pods demo、events demo crashloop-pod、logs demo crashloop-pod。"
        if _last_user_text(state).strip().lower() == "status"
        else f"Phase 1A mock echo: {_last_user_text(state)}"))]}


def _request_tool(state: MessagesState) -> dict:
    name, args = parse_demo_command(_last_user_text(state))
    return {"messages": [AIMessage(content="正在查询静态 Mock MCP 数据。",
        tool_calls=[{"name": name, "args": args, "id": f"demo-{uuid4().hex}"}])]}


async def _execute_tool(state: MessagesState, config: RunnableConfig) -> dict:
    call = state["messages"][-1].tool_calls[0]
    thread_id = config.get("configurable", {}).get("thread_id")
    response = await call_tool(call["name"], call["args"], thread_id)
    return {"messages": [ToolMessage(
        content=json.dumps(response, ensure_ascii=False),
        name=call["name"], tool_call_id=call["id"],
        status="success" if response["ok"] else "error",
    )]}


def _summarize(state: MessagesState) -> dict:
    result = json.loads(state["messages"][-1].content)
    if not result["ok"]:
        message = result["error"]
    else:
        payload = result["result"]
        if isinstance(payload, dict) and "pods" in payload:
            detail = ", ".join(f"{pod['name']}: {pod['status']}" for pod in payload["pods"])
        elif isinstance(payload, dict) and "events" in payload:
            detail = "; ".join(payload["events"])
        elif isinstance(payload, dict) and "logs" in payload:
            detail = payload["logs"]
        else:
            detail = str(payload)
        message = f"Mock MCP 结果（static-fixture，非真实 Kubernetes）：{detail}"
    return {"messages": [AIMessage(content=message)]}


def _approval(_state: MessagesState) -> dict:
    decision = interrupt({"kind": "demo_approval", "mock": True,
        "question": "Approve this simulated action? No cluster action will run.",
        "options": ["approve", "reject"]})
    approved = isinstance(decision, dict) and decision.get("decision") == "approve"
    outcome = "approved" if approved else "rejected"
    return {"messages": [AIMessage(
        content=f"Simulated approval {outcome}; no Kubernetes action was performed.")]}


def _approval_prompt(_state: MessagesState) -> dict:
    return {"messages": [AIMessage(content="Mock approval required. Review the pending request below.")]}


builder = StateGraph(MessagesState)
builder.add_node("echo", _echo)
builder.add_node("tool_request", _request_tool)
builder.add_node("tools", _execute_tool)
builder.add_node("summarize", _summarize)
builder.add_node("approval", _approval)
builder.add_node("approval_prompt", _approval_prompt)
builder.add_conditional_edges(START, _route)
builder.add_edge("echo", END)
builder.add_edge("tool_request", "tools")
builder.add_edge("tools", "summarize")
builder.add_edge("summarize", END)
builder.add_edge("approval_prompt", "approval")
builder.add_edge("approval", END)
graph = builder.compile()
