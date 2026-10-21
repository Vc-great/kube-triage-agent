"""P1-S1 锁定 SDK 离线特征测试；通过不代表安全 Gate PASS。

每例新解释器隔离 HarnessProfile；仅内存 Checkpoint、合成数据，禁止网络。
不注册 Aegra Graph，不开放 Web 或 Filesystem 模型工具。
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCENARIOS = ["normal", "short", "profile_union", "offload_failure", "timeout", "cancel",
             "state_bypass"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_native_summary_spike(scenario):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "OTEL_"))}
    env.update(LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", TRIAGE_ENV="test")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), scenario],
                            env=env, capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["scenario"] == scenario


def probe(scenario):
    def denied(*args, **kwargs):
        raise AssertionError("Summary Spike 禁止真实网络/Reader")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied

    from copy import deepcopy
    from importlib.metadata import version
    from unittest.mock import patch

    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        create_deep_agent,
        register_harness_profile,
    )
    from deepagents.backends import StateBackend
    from deepagents.backends.protocol import WriteResult
    from deepagents.backends.utils import create_file_data
    from deepagents.middleware.summarization import (
        SummarizationMiddleware,
        compute_summarization_defaults,
    )
    from langchain.agents.middleware import TodoListMiddleware
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import MemorySaver
    from pydantic import Field

    from kube_triage import deep_diagnosis as baseline
    from kube_triage.deep_diagnosis_fake import ProtocolFakeModel
    from kube_triage.deep_diagnosis_planning import MODEL_TOOLS, PlanningBoundary

    assert version("deepagents") == "0.7.28"
    baseline.call_tool = denied
    observation = {"scenario": scenario, "sdk": version("deepagents")}
    started = asyncio.Event()

    class Fake(ProtocolFakeModel):
        inputs: list = Field(default_factory=list)
        tools_seen: list = Field(default_factory=list)

        def bind_tools(self, tools, **kwargs):
            self.tools_seen.append(sorted(t.name for t in tools))
            return self

        def _reply(self, messages):
            self.inputs.append(deepcopy(messages))
            return AIMessage(content="合成观察；当前集群状态未知。")

    class SummaryFake(Fake):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            started.set()
            if scenario == "timeout":
                raise TimeoutError("synthetic summary timeout")
            if scenario == "cancel":
                await asyncio.Event().wait()
            return self._generate(messages, stop, run_manager, **kwargs)

    class FailedBackend(StateBackend):
        async def awrite(self, file_path, content):
            return WriteResult(error="synthetic offload failure")

    model, summary_model = Fake(), SummaryFake()
    backend = FailedBackend() if scenario == "offload_failure" else StateBackend()
    native = SummarizationMiddleware(model=summary_model, backend=backend,
                                    trigger=("messages", 18), keep=("messages", 8),
                                    trim_tokens_to_summarize=4000)
    assert native.name == "SummarizationMiddleware"
    assert compute_summarization_defaults(model)["trigger"] == ("tokens", 170000)
    captured = []
    import deepagents.graph as sdk_graph

    original = sdk_graph.create_agent

    def capture(*args, **kwargs):
        captured.extend(kwargs["middleware"])
        return original(*args, **kwargs)

    def build(saver):
        register_harness_profile("protocol_fake", HarnessProfile(
            excluded_tools=baseline._HIDDEN - {"write_todos"},
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ))
        with patch.object(sdk_graph, "create_agent", capture):
            return create_deep_agent(
                model=model, tools=baseline._reader_tools(), backend=backend,
                middleware=[native, TodoListMiddleware(), PlanningBoundary()],
                subagents=[], skills=None, memory=None, checkpointer=saver,
            )

    def paired(messages):
        pending = set()
        for m in messages:
            if isinstance(m, AIMessage):
                assert not pending
                pending.update(c["id"] for c in m.tool_calls)
            elif isinstance(m, ToolMessage):
                assert m.tool_call_id in pending
                pending.remove(m.tool_call_id)
            else:
                assert not pending
        assert not pending

    async def run():
        if scenario == "profile_union":
            baseline.build_graph(Fake())
        saver = MemorySaver()
        graph = build(saver)
        summaries = [m for m in captured if m.name == "SummarizationMiddleware"]
        assert summaries == ([] if scenario == "profile_union" else [native])
        observation["summary_instances"] = len(summaries)
        config = {"configurable": {"thread_id": "synthetic-summary-a"}}
        # Seed real trusted checkpoints with paired synthetic Reader history;
        # this is not a proposed public input path.
        history = []
        for i in range(5):
            history.extend([
                HumanMessage(content=f"历史合成调查 {i}"),
                AIMessage(content="", tool_calls=[{
                    "name": "pods_get", "id": f"synthetic-{i}", "args": {
                        "namespace": "kube-triage-demo", "name": "a"}}]),
                ToolMessage(content=json.dumps({"ok": True, "result": json.dumps({
                    "metadata": {"name": "a", "namespace": "kube-triage-demo",
                                 "uid": f"old-uid-{i}"},
                    "status": {"phase": "Running"}})}),
                    name="pods_get", tool_call_id=f"synthetic-{i}"),
                AIMessage(content="历史观察，不能作为当前事实。"),
            ])
        if scenario == "short":
            history = history[:4]
        await graph.aupdate_state(config, {"messages": history}, as_node="model")
        before = await graph.aget_state(config)
        user = HumanMessage(content="新一轮问候；历史 UID 不是当前证据。")
        if scenario == "state_bypass":
            # Actual installed Aegra endpoint + actual SDK graph/saver;
            # only graph acquisition and ownership DB lookup are mocked.
            from contextlib import asynccontextmanager
            from types import SimpleNamespace
            from unittest.mock import AsyncMock

            from aegra_api.api.threads import update_thread_state
            from aegra_api.models import ThreadStateUpdate, User

            @asynccontextmanager
            async def get_graph(*args, **kwargs):
                assert kwargs["access_context"] == "threads.update"
                yield graph

            forged = {"files": {"/outside/forged.md": create_file_data("synthetic forged")},
                      "_summarization_event": {
                          "cutoff_index": len(history), "file_path": None,
                          "summary_message": HumanMessage(content="SYNTHETIC_FORGED_SUMMARY")}}
            session = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(
                metadata_json={"graph_id": "synthetic-summary-only"})))
            with patch("aegra_api.services.langgraph_service.get_langgraph_service",
                       return_value=SimpleNamespace(get_graph=get_graph)):
                await update_thread_state(config["configurable"]["thread_id"],
                                          ThreadStateUpdate(values=forged),
                                          User(identity="synthetic-summary-user"), session)
            injected = (await graph.aget_state(config)).values
            assert injected["files"] == forged["files"]
            assert not model.inputs and not summary_model.inputs
            assert injected["messages"] == before.values["messages"]
            # This endpoint invocation did not persist the private field;
            # this is not proof that all input/update paths protect it.
            assert "_summarization_event" not in injected
            observation["web_gate"] = "BLOCKED: authenticated State update bypass"
            return

        if scenario == "cancel":
            task = asyncio.create_task(graph.ainvoke({"messages": [user]}, config))
            await asyncio.wait_for(started.wait(), timeout=10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif scenario == "timeout":
            with pytest.raises(TimeoutError, match="synthetic summary timeout"):
                await graph.ainvoke({"messages": [user]}, config)
        else:
            await graph.ainvoke({"messages": [user]}, config)
        saved = await graph.aget_state(config)
        state = saved.values
        assert state["messages"][:len(history)] == before.values["messages"]
        paired(state["messages"])
        assert not (await graph.aget_state({"configurable": {
            "thread_id": "synthetic-summary-b"}})).values
        if scenario in {"timeout", "cancel"}:
            assert not state.get("_summarization_event")
            assert not model.inputs
            observation["termination"] = scenario
            return
        assert all(set(names) == MODEL_TOOLS for names in model.tools_seen)
        event = state.get("_summarization_event")
        if scenario in {"short", "profile_union"}:
            assert not event and not summary_model.inputs
            assert len(model.inputs[-1]) >= len(history) + 1
            return
        assert event and len(summary_model.inputs) == 1
        assert len(model.inputs[-1]) < len(state["messages"])
        paired(model.inputs[-1])
        assert any(m.additional_kwargs.get("lc_source") == "summarization"
                   for m in model.inputs[-1])
        if scenario == "offload_failure":
            assert event["file_path"] is None
            assert not state.get("files")
            observation["source_gate"] = "BLOCKED: SDK continues after offload failure"
        else:
            path = event["file_path"]
            assert path.startswith("/conversation_history/")
            content = state["files"][path]["content"]
            assert "old-uid-0" in content and "synthetic-0" in content
            assert len(model.inputs[-1]) >= 9  # summary + pair-safe retained tail
            # Rebuild with same saver; next turn reuses native event, no extra summary.
            rebuilt = build(saver)
            await rebuilt.ainvoke({"messages": [HumanMessage(content="续答合成问候")]}, config)
            assert len(summary_model.inputs) == 1
            resumed = await rebuilt.aget_state(config)
            assert resumed.values["files"] == state["files"]
            assert resumed.values["_summarization_event"] == event
            observation.update(raw_messages=len(state["messages"]),
                               model_messages=len(model.inputs[0]),
                               cutoff=event["cutoff_index"], offload_retrievable=True)

    asyncio.run(run())
    return observation


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1]), ensure_ascii=False))
