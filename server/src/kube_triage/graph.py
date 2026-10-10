"""Key-free, side-effect-free Agent Protocol acceptance graph."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt


@tool
def get_demo_cluster_status() -> dict[str, object]:
    """Return fixed mock cluster status; never contacts Kubernetes."""
    return {
        "mock": True,
        "cluster": "phase0-demo-only",
        "status": "healthy",
        "nodes": 3,
        "source": "static fixture, not a Kubernetes query",
    }


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


def _route(state: MessagesState) -> Literal["tool_request", "approval_prompt", "echo"]:
    text = _last_user_text(state).strip().lower()
    if text.startswith("/approve-demo"):
        return "approval_prompt"
    if "status" in text or "状态" in text:
        return "tool_request"
    return "echo"


def _echo(state: MessagesState) -> dict:
    return {"messages": [AIMessage(content=f"Phase 0 mock echo: {_last_user_text(state)}")]}


def _request_tool(_state: MessagesState) -> dict:
    return {
        "messages": [
            AIMessage(
                content="Checking the deterministic mock fixture.",
                tool_calls=[
                    {
                        "name": "get_demo_cluster_status",
                        "args": {},
                        "id": f"demo-{uuid4().hex}",
                    }
                ],
            )
        ]
    }


def _summarize(_state: MessagesState) -> dict:
    return {
        "messages": [
            AIMessage(content="Mock cluster status: healthy (mock=true; no Kubernetes connection).")
        ]
    }


def _approval(_state: MessagesState) -> dict:
    decision = interrupt(
        {
            "kind": "demo_approval",
            "mock": True,
            "question": "Approve this simulated action? No cluster action will run.",
            "options": ["approve", "reject"],
        }
    )
    approved = isinstance(decision, dict) and decision.get("decision") == "approve"
    outcome = "approved" if approved else "rejected"
    return {
        "messages": [
            AIMessage(content=f"Simulated approval {outcome}; no Kubernetes action was performed.")
        ]
    }


def _approval_prompt(_state: MessagesState) -> dict:
    return {"messages": [AIMessage(content="Mock approval required. Review the pending request below.")]}


builder = StateGraph(MessagesState)
builder.add_node("echo", _echo)
builder.add_node("tool_request", _request_tool)
builder.add_node("tools", ToolNode([get_demo_cluster_status]))
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
