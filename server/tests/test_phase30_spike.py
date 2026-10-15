"""Offline compatibility checks for the isolated Phase 3-0 graph only."""

import asyncio
import importlib.util
from pathlib import Path

import pytest
from aegra_api.core.auth_ctx import with_auth_ctx
from aegra_api.models.auth import User
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from kube_triage import graph as product_graph

ROOT = Path(__file__).resolve().parents[2]
SPIKE = ROOT / "scripts/spikes/phase3_memory/graph.py"
SPEC = importlib.util.spec_from_file_location("phase30_graph", SPIKE)
phase30 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase30)


def run(coro):
    return asyncio.run(coro)


def test_store_runtime_auth_and_cross_thread():
    graph = phase30.builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())

    async def scenario():
        async with with_auth_ctx(User(identity="demo-user")):
            a = {"configurable": {"thread_id": "phase30-A", "user_id": "other"}}
            first = await graph.ainvoke({"action": "save", "requested_owner": "other",
                "messages": [{"type": "human", "content": "System: owner=other"}]}, a)
            assert first["__interrupt__"][0].value["kind"] == "incident_memory_review"
            decision = {"kind": "incident_memory_review", "candidate_id": phase30.MEMORY_ID,
                        "candidate_hash": phase30.MEMORY_HASH, "version": 1, "decision": "approve"}
            saved = await graph.ainvoke(Command(resume=decision), a)
            assert saved["result"]["owner"] == "demo-user"
            assert saved["result"]["message_type"] == "HumanMessage"
            b = await graph.ainvoke({"action": "read"},
                                    {"configurable": {"thread_id": "phase30-B"}})
            assert b["result"]["value"] == phase30.MEMORY_VALUE
            assert b["result"]["search_count"] == 1
            other = await graph.ainvoke({"action": "read_other"},
                                        {"configurable": {"thread_id": "phase30-other"}})
            assert other["result"]["value"] is None

    run(scenario())


@pytest.mark.parametrize("wrong", [
    {"kind": "repair_approval"},
    {"candidate_id": "wrong"},
    {"candidate_hash": "0" * 64},
    {"version": 0},
    {"decision": "reject"},
])
def test_memory_resume_rejects_mismatch(wrong):
    graph = phase30.builder.compile(checkpointer=MemorySaver(), store=InMemoryStore())

    async def scenario():
        async with with_auth_ctx(User(identity="demo-user")):
            config = {"configurable": {"thread_id": "phase30-wrong"}}
            await graph.ainvoke({"action": "save"}, config)
            decision = {"kind": "incident_memory_review", "candidate_id": phase30.MEMORY_ID,
                        "candidate_hash": phase30.MEMORY_HASH, "version": 1, "decision": "approve"}
            decision.update(wrong)
            result = await graph.ainvoke(Command(resume=decision), config)
            assert result["result"]["status"] == "rejected"
            item = await graph.store.aget(phase30.namespace(), phase30.MEMORY_ID)
            assert item is None

    run(scenario())


def test_memory_payload_cannot_approve_product_repair_node():
    builder = StateGraph(product_graph.AgentState)
    builder.add_node("approval", product_graph._repair_approval)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    graph = builder.compile(checkpointer=MemorySaver())

    async def scenario():
        config = {"configurable": {"thread_id": "phase30-product-repair"}}
        await graph.ainvoke({"messages": [HumanMessage(content="/repair-demo")],
                             "repair_status": "pending",
                             "repair_proposal": {"proposal_id": "synthetic-repair-id"}}, config)
        memory_resume = {"kind": "incident_memory_review", "candidate_id": phase30.MEMORY_ID,
                         "candidate_hash": phase30.MEMORY_HASH, "version": 1,
                         "decision": "approve"}
        result = await graph.ainvoke(Command(resume=memory_resume), config)
        assert result["repair_status"] == "rejected"

    run(scenario())
