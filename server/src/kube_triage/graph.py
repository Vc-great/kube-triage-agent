"""Read-only diagnosis plus one explicit, approval-gated scale exercise."""

from __future__ import annotations

import json
import logging
import time
from typing import Literal, NotRequired
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from kube_triage import repair
from kube_triage.llm import chat_model, enabled
from kube_triage.mcp_client import NAMESPACE, _allowed_tools, call_tool
from kube_triage.prompts import SYSTEM_PROMPT

MAX_TOOL_CALLS = 6
MAX_MODEL_DECISIONS = 4
audit = logging.getLogger("kube_triage.audit")


class AgentState(MessagesState):
    repair_proposal: NotRequired[dict | None]
    repair_status: NotRequired[str]
    repair_result: NotRequired[dict | None]


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


def _route(state: MessagesState) -> Literal[
        "llm", "tool_request", "approval_prompt", "repair_prepare", "echo"]:
    text = _last_user_text(state).strip().lower()
    if text == "/repair-demo":
        return "repair_prepare"
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


def _repair_stop(message: str, status: str = "denied") -> dict:
    return {"repair_proposal": None, "repair_status": status, "repair_result": None,
            "messages": [AIMessage(content=message)]}


async def _repair_prepare(_state: AgentState) -> dict:
    if not repair.repair_enabled():
        return _repair_stop("受控恢复功能未启用（REPAIR_ENABLED=false）；没有执行 Kubernetes 写入。")
    try:
        deployment = await repair.read_deployment()
        uid = repair.validate_deployment(deployment)
        scale = await repair.read_scale()
        if (scale["uid"] != uid or scale["replicas"] != 0 or
                deployment["spec"].get("replicas") != 0):
            return _repair_stop("目标 UID 或初始副本数不符；只允许从 0 提案恢复到 1。")
    except Exception as exc:  # noqa: BLE001 - fail closed for any upstream format/transport error
        return _repair_stop(f"预检失败（{repair.safe_error(exc)}）；没有生成审批或执行写入。")
    proposal = {"proposal_id": uuid4().hex, "apiVersion": repair.API_VERSION,
                "namespace": repair.NAMESPACE, "kind": repair.KIND, "name": repair.NAME,
                "uid": uid, "before_replicas": 0, "target_replicas": 1,
                "impact": "只把本项目演示 Deployment 从 0 副本扩到 1；Pod Ready 需另行验证。",
                "source": "explicit-user-command", "simulated": repair.simulated()}
    return {"repair_proposal": proposal, "repair_status": "pending", "repair_result": None,
            "messages": [AIMessage(content="已核实固定演示资源当前为 0 副本。请在下方审阅提案。") ]}


def _after_repair_prepare(state: AgentState) -> Literal["repair_approval", "__end__"]:
    return "repair_approval" if state.get("repair_status") == "pending" else END


def _repair_approval(state: AgentState, config: RunnableConfig) -> dict:
    proposal = state.get("repair_proposal")
    if not proposal or state.get("repair_status") != "pending":
        return _repair_stop("审批状态缺失；拒绝执行。")
    decision = interrupt({"kind": "repair_approval", "proposal": proposal,
        "question": "是否批准把 kube-triage-demo/Deployment/triage-repair-demo 从 0 扩到 1？",
        "options": ["approve", "reject"]})
    valid = (isinstance(decision, dict) and set(decision) == {"decision", "proposal_id"}
             and decision.get("proposal_id") == proposal["proposal_id"])
    approved = valid and decision["decision"] == "approve"
    thread_id = config.get("configurable", {}).get("thread_id")
    audit.info(json.dumps({"event": "repair_decision", "thread_id": thread_id,
        "proposal_id": proposal["proposal_id"], "namespace": repair.NAMESPACE,
        "name": repair.NAME, "decision": "approve" if approved else "reject_or_invalid"},
        ensure_ascii=False))
    if not approved:
        return {"repair_status": "rejected", "messages": [AIMessage(content=(
            "审批拒绝或 proposal_id/参数无效；没有执行 Kubernetes 写入。"))]}
    return {"repair_status": "approved", "messages": [AIMessage(content=(
        "审批已通过；执行节点将重新检查目标与副本数。"))]}


def _after_repair_approval(state: AgentState) -> Literal["repair_execute", "__end__"]:
    return "repair_execute" if state.get("repair_status") == "approved" else END


async def _repair_execute(state: AgentState, config: RunnableConfig) -> dict:
    start = time.monotonic()
    proposal = state.get("repair_proposal") or {}
    thread_id = config.get("configurable", {}).get("thread_id")
    fixed = {"apiVersion": repair.API_VERSION, "namespace": repair.NAMESPACE,
             "kind": repair.KIND, "name": repair.NAME, "before_replicas": 0,
             "target_replicas": 1, "source": "explicit-user-command"}
    if (not repair.repair_enabled() or state.get("repair_status") != "approved" or
            not proposal.get("proposal_id") or not proposal.get("uid") or
            proposal.get("simulated") != repair.simulated() or
            any(proposal.get(key) != value for key, value in fixed.items())):
        return _repair_stop("执行前安全状态校验失败；没有执行 Kubernetes 写入。")
    write_attempted = False
    write_reply = False
    classification = "写结果未知/失败"
    detail = ""
    pod_status = "unknown"
    observed = None
    try:
        deployment = await repair.read_deployment()
        repair.validate_deployment(deployment, proposal["uid"])
        before = await repair.read_scale()
        if (before["uid"] != proposal["uid"] or
                deployment["spec"].get("replicas") != before["replicas"]):
            raise ValueError("Scale UID changed")
        if before["replicas"] == 0:
            write_attempted = True
            try:
                await repair.write_scale_once()
                write_reply = True
            except Exception as exc:  # noqa: BLE001 - response loss may follow a committed update
                detail = f"写请求回执未知（{repair.safe_error(exc)}）；已停止重试并尝试只读回查。"
        elif before["replicas"] == 1:
            detail = "已达到目标副本数；未再次写入（no-op）。"
        else:
            raise ValueError("Pre-execution replicas is neither 0 nor 1")
        try:
            after = await repair.read_scale()
            if after["uid"] != proposal["uid"]:
                raise ValueError("Scale UID changed during verification")
            observed = after["replicas"]
            if observed == 1:
                pod_status = await repair.pod_readiness(thread_id)
                if write_attempted and not write_reply:
                    classification = "写结果未知/失败"
                    detail += " 回查为 1，但不能证明本次请求是唯一写入来源。"
                elif pod_status == "ready":
                    classification = "写操作已成功且可验证" if write_attempted else "目标已达成（无重复写入）"
                elif pod_status.startswith("unknown"):
                    classification = ("写请求已回执且 scale=1；Pod Ready 未知" if write_attempted
                                      else "目标已达成；Pod Ready 未知")
                else:
                    classification = "写请求提交但 Pod 尚未 Ready" if write_attempted else "目标已达成但 Pod 尚未 Ready"
            else:
                detail += f" 回查副本数为 {observed}，目标未达成。"
        except Exception as exc:  # noqa: BLE001 - verification failure stays uncertain
            detail += f" 回查失败（{repair.safe_error(exc)}）。"
    except Exception as exc:  # noqa: BLE001 - fail closed before any write
        detail = f"执行前检查失败（{repair.safe_error(exc)}）；没有发出写请求。"
    result = {"classification": classification, "write_attempted": write_attempted,
              "write_response_received": write_reply, "observed_replicas": observed,
              "pod_ready": pod_status, "detail": detail, "simulated": repair.simulated()}
    audit.info(json.dumps({"event": "repair_result", "thread_id": thread_id,
        "proposal_id": proposal["proposal_id"], "namespace": repair.NAMESPACE,
        "name": repair.NAME, "classification": classification,
        "write_attempted": write_attempted,
        "duration_ms": round((time.monotonic() - start) * 1000)}, ensure_ascii=False))
    return {"repair_status": "finished", "repair_result": result,
            "messages": [AIMessage(content=(f"{'离线模拟；' if repair.simulated() else ''}"
                                         f"{classification}。scale={observed}；Pod Ready：{pod_status}。"
                                         f"{detail} 0→1 只是演示，不代表故障根因已修复。"))]}


builder = StateGraph(AgentState)
builder.add_node("llm", _llm)
builder.add_node("echo", _echo)
builder.add_node("tool_request", _request_tool)
builder.add_node("tools", _execute_tool)
builder.add_node("summarize", _summarize)
builder.add_node("approval", _approval)
builder.add_node("approval_prompt", _approval_prompt)
builder.add_node("repair_prepare", _repair_prepare)
builder.add_node("repair_approval", _repair_approval)
builder.add_node("repair_execute", _repair_execute)
builder.add_conditional_edges(START, _route)
builder.add_conditional_edges("llm", _after_llm)
builder.add_edge("echo", END)
builder.add_edge("tool_request", "tools")
builder.add_conditional_edges("tools", _after_tools)
builder.add_edge("summarize", END)
builder.add_edge("approval_prompt", "approval")
builder.add_edge("approval", END)
builder.add_conditional_edges("repair_prepare", _after_repair_prepare)
builder.add_conditional_edges("repair_approval", _after_repair_approval)
builder.add_edge("repair_execute", END)
graph = builder.compile()
