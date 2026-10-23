"""原 Agent 的 Summary/Memory/HITL 在真实隔离 PG、业务开关双开下回归。"""

import asyncio
import os
from uuid import uuid4

import pytest
from aegra_api.core.auth_ctx import with_auth_ctx
from aegra_api.models.auth import User
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.types import Command
from test_app_persistence import pg as pg  # noqa: PLC0414 - pytest fixture re-export
from test_context_gate_b import FakeModel, history
from test_incident_memory import attestations, round_messages
from test_phase3b import demo_deployment

from kube_triage import app_storage, repair
from kube_triage import graph as agent
from kube_triage import incident_memory as memory
from kube_triage.mcp_client import ALLOWED_TOOLS


@pytest.mark.parametrize("summary_failure", [False, True])
def test_summary_preserves_pg_checkpoint_and_business_history(pg, monkeypatch, summary_failure):
    monkeypatch.setenv("CONTEXT_WINDOW_ENABLED", "true")
    monkeypatch.setenv("CONTEXT_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("CONTEXT_ESTIMATED_TOTAL_BUDGET", "6500")
    model = FakeModel(TimeoutError()) if summary_failure else FakeModel()
    monkeypatch.setattr(agent, "chat_model", lambda: model)

    async def tools():
        return {name: object() for name in ALLOWED_TOOLS}

    monkeypatch.setattr(agent, "_allowed_tools", tools)

    async def scenario():
        async with AsyncPostgresSaver.from_conn_string(os.environ["ISSUE78_TEST_DATABASE_URL"]) as cp:
            await cp.setup()
            graph = agent.builder.compile(checkpointer=cp)
            thread = str(uuid4())
            config = {"configurable": {"thread_id": thread}}
            raw = [*history(), HumanMessage(content="现在怎样？")]
            await graph.aupdate_state(config, {"messages": raw}, as_node="__start__")
            before = await graph.aget_state(config)
            async def read():
                state = await graph.aget_state(config)
                return {"values": {"messages": [m.model_dump(mode="json")
                                                  for m in state.values["messages"]]},
                        "checkpoint": state.config["configurable"]}, {
                            "metadata": {"graph_id": "agent"}}, {"status": "success"}
            await app_storage.sync_history(thread, read)
            old = await app_storage.get_history(thread, 200, 0, None)
            result = await graph.ainvoke(None, config)
            after = await graph.aget_state(config)
            assert [m.id for m in after.values["messages"][:len(raw)]] == [
                m.id for m in before.values["messages"]]
            assert len(after.values["messages"]) == len(raw) + 1
            assert len(model.main_inputs[0]) < len(raw)
            assert model.summary_calls == 1
            assert result["context_summary"]["status"] == ("failed" if summary_failure else "ready")
            await app_storage.sync_history(thread, read)
            saved = await app_storage.get_history(thread, 200, 0, None)
            assert len(saved["messages"]) == len(old["messages"]) + 1
            assert all(a["id"] == b["id"] for a, b in zip(old["messages"], saved["messages"]))
    asyncio.run(scenario())


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_memory_pg_review_read_and_revoke(pg, monkeypatch, decision):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_PROVENANCE_SECRET", "synthetic-provenance-secret-32chars-31")

    async def scenario():
        url = os.environ["ISSUE78_TEST_DATABASE_URL"]
        async with (AsyncPostgresSaver.from_conn_string(url) as cp,
                    AsyncPostgresStore.from_conn_string(url) as store,
                    with_auth_ctx(User(identity="demo-user"))):
            await cp.setup()
            await store.setup()
            graph = agent.builder.compile(checkpointer=cp, store=store)
            thread = str(uuid4())
            config = {"configurable": {"thread_id": thread}}
            messages = round_messages()
            pending = await graph.ainvoke({"messages": messages,
                "reader_attestations": attestations(messages, thread)}, config)
            payload = pending["__interrupt__"][0].value
            # Resume using a newly compiled graph from the actual PG checkpoint.
            graph = agent.builder.compile(checkpointer=cp, store=store)
            approved = await graph.ainvoke(Command(resume={"kind": payload["kind"], "candidate_id": payload["candidate_id"],
                "candidate_hash": payload["candidate_hash"], "schema_version": 1, "decision": decision}), config)
            key = payload["candidate_id"]
            item = await store.aget(memory.store_namespace("demo-user"), key)
            if decision == "reject":
                assert approved["memory_status"] == "rejected" and item is None
                return
            assert approved["memory_status"] == "stored" and item.value["status"] == "active"
            assert item.value["review"]["reviewer"] == "demo-user"
            pending = await graph.ainvoke({"messages": [HumanMessage(
                content=f"/forget-incident {key}")]}, config)
            revoke = pending["__interrupt__"][0].value
            result = await graph.ainvoke(Command(resume={"kind": revoke["kind"], "memory_id": key,
                "record_hash": revoke["record_hash"], "schema_version": 1, "decision": "approve"}), config)
            assert result["memory_status"] == "revoked"
            assert (await store.aget(memory.store_namespace("demo-user"), key)).value["status"] == "revoked"
    asyncio.run(scenario())


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_hitl_pg_resume_keeps_mock_write_gate(pg, monkeypatch, decision):
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("REPAIR_SIMULATED", "true")
    monkeypatch.setenv("REPAIR_ENABLED", "true")
    writes = []
    async def deployment():
        data = demo_deployment()
        data["spec"]["replicas"] = int(bool(writes))
        return data
    async def scale():
        return {"replicas": int(bool(writes)), "uid": "demo-uid"}
    async def write():
        writes.append("mock-only")
    async def ready(_):
        return "ready"
    monkeypatch.setattr(repair, "read_deployment", deployment)
    monkeypatch.setattr(repair, "read_scale", scale)
    monkeypatch.setattr(repair, "write_scale_once", write)
    monkeypatch.setattr(repair, "pod_readiness", ready)
    async def scenario():
        async with AsyncPostgresSaver.from_conn_string(os.environ["ISSUE78_TEST_DATABASE_URL"]) as cp:
            await cp.setup()
            config = {"configurable": {"thread_id": str(uuid4())}}
            graph = agent.builder.compile(checkpointer=cp)
            pending = await graph.ainvoke({"messages": [HumanMessage(content="/repair-demo")]}, config)
            assert (await graph.aget_state(config)).next == ("repair_approval",)
            graph = agent.builder.compile(checkpointer=cp)
            result = await graph.ainvoke(Command(resume={"decision": decision,
                "proposal_id": pending["repair_proposal"]["proposal_id"]}), config)
            if decision == "approve":
                assert writes == ["mock-only"] and result["repair_result"]["simulated"]
            else:
                assert not writes and result["repair_status"] == "rejected"
    asyncio.run(scenario())
