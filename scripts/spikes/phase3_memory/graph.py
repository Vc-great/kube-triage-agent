"""Synthetic Phase 3-0 probe. No model, MCP, Kubernetes or product graph imports."""

from __future__ import annotations

import hashlib
import json

from aegra_api.core.auth_ctx import get_auth_ctx
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

MEMORY_ID = "synthetic-phase30-001"
MEMORY_VALUE = {"memory_id": MEMORY_ID, "summary": "Synthetic incident only", "workload": "synthetic-workload", "version": 1}
MEMORY_HASH = hashlib.sha256(json.dumps(MEMORY_VALUE, sort_keys=True).encode()).hexdigest()


class ProbeState(MessagesState, total=False):
    action: str
    message: str
    requested_owner: str
    result: dict


def owner() -> str:
    ctx = get_auth_ctx()
    identity = getattr(getattr(ctx, "user", None), "identity", None)
    if identity != "demo-user":
        raise PermissionError("Missing trusted demo identity")
    return identity


def namespace() -> tuple[str, ...]:
    return ("kube-triage", owner(), "incidents", "v1")


def route(state: ProbeState) -> str:
    return "memory" if state.get("action") in {"save", "delete"} else (
        "repair" if state.get("action") == "repair" else "read")


async def memory(state: ProbeState, runtime: Runtime) -> dict:
    ns = namespace()
    action = state["action"]
    decision = interrupt({"kind": "incident_memory_review", "candidate_id": MEMORY_ID,
                          "candidate_hash": MEMORY_HASH, "version": 1,
                          "decision": ["approve", "reject"]})
    expected = {"kind": "incident_memory_review", "candidate_id": MEMORY_ID,
                "candidate_hash": MEMORY_HASH, "version": 1, "decision": "approve"}
    if decision != expected:
        return {"result": {"status": "rejected", "owner": owner()}}
    if action == "save":
        await runtime.store.aput(ns, MEMORY_ID, MEMORY_VALUE)
    else:
        await runtime.store.adelete(ns, MEMORY_ID)
    return {"result": {"status": action, "owner": owner(), "namespace": list(ns),
                       "key": MEMORY_ID,
                       "message_type": type(state["messages"][0]).__name__ if state.get("messages") else None}}


async def read(state: ProbeState, runtime: Runtime) -> dict:
    ns = namespace()
    if state.get("action") == "read_other":
        ns = ("kube-triage", "other", "incidents", "v1")
    item = await runtime.store.aget(ns, MEMORY_ID)
    found = await runtime.store.asearch(ns, filter={"version": 1}, limit=3)
    return {"result": {"owner": owner(), "namespace": list(ns), "key": MEMORY_ID,
                       "value": item.value if item else None, "search_count": len(found)}}


def repair(_state: ProbeState) -> dict:
    proposal_id = "synthetic-repair-proposal"
    decision = interrupt({"kind": "repair_approval", "proposal": {"proposal_id": proposal_id,
                          "simulated": True}, "options": ["approve", "reject"]})
    # Mirrors the product's exact-key and proposal_id checks, without any
    # repair_execute node or Kubernetes capability.
    valid = (isinstance(decision, dict) and set(decision) == {"decision", "proposal_id"}
             and decision.get("proposal_id") == proposal_id
             and decision.get("decision") == "approve")
    return {"result": {"status": "simulated_repair_approved" if valid else "rejected"}}


builder = StateGraph(ProbeState)
builder.add_node("memory", memory)
builder.add_node("read", read)
builder.add_node("repair", repair)
builder.add_conditional_edges(START, route)
builder.add_edge("memory", END)
builder.add_edge("read", END)
builder.add_edge("repair", END)
graph = builder.compile()
