"""Issue #72：受信执行 nonce、原生 Checkpoint 重放与异步入口负测。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.runnables import Runnable

from kube_triage import deep_diagnosis_review as review


class InspectGraph(Runnable):
    def __init__(self):
        self.executions = []

    def invoke(self, input, config=None, **kwargs):
        raise AssertionError("不允许绕过异步 Host 入口")

    async def ainvoke(self, input, config=None, **kwargs):
        execution = review._EXECUTION.get()
        assert execution and execution.active
        self.executions.append(execution)
        await asyncio.sleep(0)
        return review._scope(input, SimpleNamespace(config=config))


def test_host_entry_ignores_client_nonce_and_keeps_caller_context_private():
    async def run():
        native = InspectGraph()
        graph = review._ReviewGraph(native)
        caller = review._EXECUTION.get()
        state = {"messages": [HumanMessage(id="same-human", content="相同请求")]}
        config = {"configurable": {"thread_id": "same-thread"},
                  "run_id": UUID("00000000-0000-0000-0000-000000000001")}
        first = await graph.ainvoke(state, config)
        old_nonce = native.executions[0].nonce
        state.update(_execution_nonce=old_nonce, turn_id=first["turn_id"])
        config["configurable"].update(_execution_nonce=old_nonce, turn_id=first["turn_id"])
        second = await graph.with_config(config).ainvoke(state, context={"nonce": old_nonce})
        assert first["turn_id"] != second["turn_id"]
        assert all(not execution.active for execution in native.executions)
        assert review._EXECUTION.get() is caller
    asyncio.run(run())


def test_host_abatch_gives_identical_concurrent_inputs_distinct_scopes():
    async def run():
        native = InspectGraph()
        graph = review._ReviewGraph(native)
        caller = review._EXECUTION.get()
        inputs = [{"messages": [HumanMessage(id="same-human", content="相同请求")]}] * 2
        scopes = await graph.abatch(inputs, {"configurable": {"thread_id": "same-thread"}})
        assert scopes[0]["turn_id"] != scopes[1]["turn_id"]
        assert all(not execution.active for execution in native.executions)
        assert review._EXECUTION.get() is caller
    asyncio.run(run())


def test_unsupported_entries_never_execute_without_host_context():
    async def run():
        native = InspectGraph()
        graph = review._ReviewGraph(native)
        with pytest.raises(NotImplementedError):
            graph.invoke({})
        with pytest.raises(NotImplementedError):
            list(graph.stream({}))
        with pytest.raises(NotImplementedError):
            await anext(graph.astream_events({}, version="v3"))
        assert not native.executions and review._EXECUTION.get() is None
    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["same_request", "concurrent", "checkpoint_replay",
                                     "stream", "events", "cancel", "stream_close", "failure",
                                     "unwrapped"])
def test_native_execution_context(scenario):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "OTEL_"))}
    env.update(LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", TRIAGE_ENV="test")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), scenario],
                            env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


def probe(scenario):
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph.message import REMOVE_ALL_MESSAGES
    from pydantic import Field

    from kube_triage.deep_diagnosis_fake import ProtocolFakeModel

    def denied(*args, **kwargs):
        raise AssertionError("执行上下文测试禁止网络")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    started, cancelled = asyncio.Event(), asyncio.Event()
    reads = []

    async def reader(name, args, thread_id=None):
        reads.append(name)
        return {"ok": True, "result": json.dumps({"kind": "Pod", "metadata": {
            "namespace": "kube-triage-demo", "name": "a", "uid": "synthetic-uid-a"},
            "status": {"phase": "Running"}})}

    review.baseline.call_tool = reader

    class Fake(ProtocolFakeModel):
        is_reviewer: bool = False
        executions: list = Field(default_factory=list)
        manifests: list = Field(default_factory=list)
        fail_next: bool = False

        def _reply(self, messages):
            execution = review._EXECUTION.get()
            assert execution and execution.active
            self.executions.append(execution)
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("synthetic parent failure")
            if self.is_reviewer:
                manifest = json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))
                self.manifests.append(manifest)
                return AIMessage(content=json.dumps({"verdict": "INSUFFICIENT",
                    "supported_claims": [], "contradictions": [], "evidence_refs": ["read-1"],
                    "unknowns": ["缺少指标"], "recommended_next_read": "", "reason": "合成证据不足"}))
            replies = [m for m in messages if isinstance(m, ToolMessage)]
            if not any(m.name == "pods_get" for m in replies):
                return AIMessage(content="", tool_calls=[{"name": "pods_get", "id": "read-1",
                    "args": {"namespace": "kube-triage-demo", "name": "a"}}])
            if not any(m.name == "task" for m in replies):
                return AIMessage(content="", tool_calls=[{"name": "task", "id": "task-1",
                    "args": {"description": "合成候选", "subagent_type": "evidence-reviewer"}}])
            return AIMessage(content="仅合成候选，根因未证实。")

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            if self.is_reviewer and scenario == "cancel":
                self.executions.append(review._EXECUTION.get())
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return self._generate(messages, stop, run_manager, **kwargs)

    parent, reviewer = Fake(fail_next=scenario == "failure"), Fake(is_reviewer=True)
    graph = review.build_graph(parent, reviewer,
        checkpointer=MemorySaver() if scenario == "checkpoint_replay" else None)

    def input_state():
        return {"messages": [HumanMessage(id="same-human", content="调查 Pod/a")]}

    config = {"configurable": {"thread_id": "synthetic-a"},
              "run_id": UUID("00000000-0000-0000-0000-000000000001")}

    async def run():
        assert review._EXECUTION.get() is None
        if scenario == "same_request":
            first = await graph.ainvoke(input_state(), config)
            second = await graph.ainvoke(input_state(), config)
            assert all("review_status=COMPLETED" in r["messages"][-1].content for r in [first, second])
            assert len(reads) == len(reviewer.manifests) == 2
            assert reviewer.manifests[0]["scope"] != reviewer.manifests[1]["scope"]
        elif scenario == "concurrent":
            results = await graph.abatch([input_state(), input_state()], config)
            assert all("review_status=COMPLETED" in r["messages"][-1].content for r in results)
            assert len(reviewer.manifests) == 2
            assert reviewer.manifests[0]["scope"] != reviewer.manifests[1]["scope"]
        elif scenario == "checkpoint_replay":
            first = await graph.ainvoke(input_state(), config)
            assert "review_status=COMPLETED" in first["messages"][-1].content
            old = [deepcopy(m) for m in first["messages"] if isinstance(m, HumanMessage)
                   or isinstance(m, AIMessage) and any(c["name"] == "pods_get" for c in m.tool_calls)
                   or isinstance(m, ToolMessage) and m.name == "pods_get"]
            old.append(AIMessage(content="", tool_calls=[{"name": "task", "id": "replay-task",
                "args": {"description": "合成候选", "subagent_type": "evidence-reviewer"}}]))
            # Actual checkpoint State update bypasses before_agent on Resume.
            # Both Human ID/content and the Reader call ID/MAC remain unchanged.
            await graph.aupdate_state(config, {"messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES), *old]}, as_node="model")
            replay = await graph.ainvoke(None, config)
            assert len(reads) == 1 and len(reviewer.manifests) == 1
            reply = next(m for m in replay["messages"] if isinstance(m, ToolMessage)
                         and m.tool_call_id == "replay-task")
            assert json.loads(reply.content)["review_status"] == "FAILED"
            assert "verdict=UNKNOWN" in replay["messages"][-1].content
            assert not (await graph.aget_state({"configurable": {"thread_id": "synthetic-b"}})).values
        elif scenario == "stream":
            chunks = [chunk async for chunk in graph.astream(input_state(), config, stream_mode="values")]
            assert "review_status=COMPLETED" in chunks[-1]["messages"][-1].content
        elif scenario == "events":
            events = [event async for event in graph.astream_events(input_state(), config, version="v2")]
            outputs = [e["data"].get("output") for e in events if e["event"] == "on_chain_end"]
            states = [o for o in outputs if isinstance(o, dict) and "messages" in o]
            assert "review_status=COMPLETED" in states[-1]["messages"][-1].content
        elif scenario == "cancel":
            running = asyncio.create_task(graph.ainvoke(input_state(), config))
            await asyncio.wait_for(started.wait(), 5)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            assert cancelled.is_set()
        elif scenario == "stream_close":
            stream = graph.astream(input_state(), config, stream_mode="values")
            for _ in range(10):
                await anext(stream)
                if parent.executions:
                    break
            assert parent.executions
            await stream.aclose()
        elif scenario == "failure":
            with pytest.raises(RuntimeError, match="synthetic parent failure"):
                await graph.ainvoke(input_state(), config)
            good = await graph.ainvoke(input_state(), config)
            assert "review_status=COMPLETED" in good["messages"][-1].content
        elif scenario == "unwrapped":
            with pytest.raises(review.ReviewFailure, match="受信执行轮次"):
                await graph._graph.ainvoke(input_state(), config)
            assert not parent.executions and not reviewer.executions and not reads
        assert review._EXECUTION.get() is None
        assert all(not execution.active for execution in parent.executions + reviewer.executions)
        assert all(execution.nonce not in str(manifest)
                   for execution in parent.executions for manifest in reviewer.manifests)

    asyncio.run(run())


if __name__ == "__main__":
    probe(sys.argv[1])
