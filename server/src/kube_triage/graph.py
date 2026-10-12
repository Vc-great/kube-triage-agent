"""One read-only graph: legacy mock commands or an LLM/MCP ReAct loop."""

from __future__ import annotations

import json
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from kube_triage.llm import chat_model, enabled
from kube_triage.mcp_client import NAMESPACE, _allowed_tools, call_tool
from kube_triage.prompts import SYSTEM_PROMPT

MAX_TOOL_CALLS = 6
MAX_MODEL_DECISIONS = 4


def _current_turn(state: MessagesState) -> list:
    messages = state["messages"]
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _counts(state: MessagesState) -> tuple[int, int]:
    turn = _current_turn(state)
    decisions = sum(isinstance(m, AIMessage) and m.name == "triage_llm" for m in turn)
    calls = sum(isinstance(m, ToolMessage) for m in turn)
    return decisions, calls


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
    if not parts or parts[0] not in {"pods", "pod", "events", "logs"}:
        return None
    if parts[0] == "pods" and len(parts) == 2:
        return "pods_list_in_namespace", {"namespace": parts[1]}
    if parts[0] == "events" and len(parts) == 2:
        return "events_list", {"namespace": parts[1]}
    if parts[0] in {"pod", "logs"} and len(parts) == 3:
        name = "pods_get" if parts[0] == "pod" else "pods_log"
        args = {"namespace": parts[1], "name": parts[2]}
        if name == "pods_log":
            args["tail"] = 20
        return name, args
    return "invalid_command", {"namespace": parts[1] if len(parts) > 1 else ""}


def _route(state: MessagesState) -> Literal["llm", "tool_request", "approval_prompt", "echo"]:
    text = _last_user_text(state).strip().lower()
    if text.startswith("/approve-demo"):
        return "approval_prompt"
    if enabled():
        return "llm"
    if parse_demo_command(text):
        return "tool_request"
    return "echo"


def _echo(state: MessagesState) -> dict:
    return {"messages": [AIMessage(content=(
        f"试试 pods {NAMESPACE}、pod {NAMESPACE} crashloop-pod、"
        f"events {NAMESPACE}、logs {NAMESPACE} crashloop-pod。"
        if _last_user_text(state).strip().lower() == "status"
        else f"Phase 1B echo: {_last_user_text(state)}"))]}


def _request_tool(state: MessagesState) -> dict:
    name, args = parse_demo_command(_last_user_text(state))
    return {"messages": [AIMessage(content="正在查询 Kubernetes MCP 工具。",
        tool_calls=[{"name": name, "args": args, "id": f"demo-{uuid4().hex}"}])]}


async def _execute_tool(state: MessagesState, config: RunnableConfig) -> dict:
    calls = state["messages"][-1].tool_calls
    thread_id = config.get("configurable", {}).get("thread_id")
    used = _counts(state)[1]
    results = []
    for call in calls:
        if used >= MAX_TOOL_CALLS:
            response = {"ok": False, "error": "本轮工具调用预算已用尽（6 次）。",
                        "error_type": "budget"}
        else:
            response = await call_tool(call["name"], call["args"], thread_id)
            used += 1
        results.append(ToolMessage(
            content=json.dumps(response, ensure_ascii=False),
            name=call["name"], tool_call_id=call["id"],
            status="success" if response["ok"] else "error",
        ))
    return {"messages": results}


async def _llm(state: MessagesState) -> dict:
    decisions, _used = _counts(state)
    if decisions >= MAX_MODEL_DECISIONS:
        return {"messages": [AIMessage(content=(
            "已达到本轮模型决策上限（4 轮）。请根据上方证据人工核查；"
            "若证据不足，不能断言根因。"))]}
    try:
        model = chat_model()
        tools = list((await _allowed_tools()).values())
        model = model.bind_tools(tools)
        reply = await model.ainvoke([SystemMessage(content=SYSTEM_PROMPT),
                                      *state["messages"]])
        if not isinstance(reply, AIMessage):
            raise TypeError("LLM returned a non-AI message")
        if reply.invalid_tool_calls:
            return {"messages": [AIMessage(content=(
                "模型返回了无法解析的 Tool Call；请确认模型服务支持标准 Tool Calling。"))]}
        if not reply.tool_calls and not reply.content:
            return {"messages": [AIMessage(content=(
                "模型未返回内容或标准 Tool Call；本次诊断未完成。"))]}
        reply.name = "triage_llm"
        return {"messages": [reply]}
    except ValueError as exc:
        return {"messages": [AIMessage(content=str(exc))]}
    except Exception as exc:  # noqa: BLE001 - provider/MCP errors vary by SDK
        name = type(exc).__name__.lower()
        if "ratelimit" in name or "429" in str(exc):
            detail = "模型请求被限流（429）"
        elif "timeout" in name:
            detail = "模型请求超时"
        elif "connect" in name or isinstance(exc, OSError):
            detail = "模型或 MCP 连接失败"
        else:
            detail = "模型调用或 MCP 工具发现失败"
        return {"messages": [AIMessage(content=f"{detail}；本次诊断未完成。")]}


def _after_llm(state: MessagesState) -> Literal["tools", "__end__"]:
    return "tools" if state["messages"][-1].tool_calls else END


def _after_tools(state: MessagesState) -> Literal["llm", "summarize"]:
    return "llm" if enabled() else "summarize"


def _summarize(state: MessagesState) -> dict:
    result = json.loads(state["messages"][-1].content)
    if not result["ok"]:
        message = result["error"]
    else:
        message = result["result"]
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
builder.add_node("llm", _llm)
builder.add_node("echo", _echo)
builder.add_node("tool_request", _request_tool)
builder.add_node("tools", _execute_tool)
builder.add_node("summarize", _summarize)
builder.add_node("approval", _approval)
builder.add_node("approval_prompt", _approval_prompt)
builder.add_conditional_edges(START, _route)
builder.add_conditional_edges("llm", _after_llm)
builder.add_edge("echo", END)
builder.add_edge("tool_request", "tools")
builder.add_conditional_edges("tools", _after_tools)
builder.add_edge("summarize", END)
builder.add_edge("approval_prompt", "approval")
builder.add_edge("approval", END)
graph = builder.compile()
