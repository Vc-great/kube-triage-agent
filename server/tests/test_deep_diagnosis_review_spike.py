"""Issue #72 S1：固定 SDK 的原生委派与 State 负测，独立解释器隔离 Profile。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["normal", "state", "read_file", "write_file",
                                     "pods_get", "execute", "task", "repair"])
def test_review_sdk_spike(scenario):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "OTEL_"))}
    env.update(LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", TRIAGE_ENV="test")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), scenario],
                            env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["scenario"] == scenario


def probe(scenario):
    def denied(*args, **kwargs):
        raise AssertionError("Reviewer Spike 禁止网络/真实 Reader")

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
    from deepagents.backends.utils import create_file_data
    from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command
    from pydantic import Field

    from kube_triage import deep_diagnosis as baseline
    from kube_triage.deep_diagnosis_fake import ProtocolFakeModel
    from kube_triage.deep_diagnosis_planning import MODEL_TOOLS

    assert version("deepagents") == "0.7.28"
    assert version("aegra-cli") == "0.10.8"
    baseline.call_tool = denied
    observed, assembled = [], []

    class Fake(ProtocolFakeModel):
        role: str
        inputs: list = Field(default_factory=list)
        tools_seen: list = Field(default_factory=list)

        def bind_tools(self, tools, **kwargs):
            self.tools_seen.append([t.name for t in tools])
            return self

        def _reply(self, messages):
            self.inputs.append(deepcopy(messages))
            if self.role == "parent":
                if not any(isinstance(m, ToolMessage) for m in messages):
                    return AIMessage(content="", tool_calls=[{
                        "name": "task", "id": "native-task-1", "args": {
                            "description": "UNTRUSTED_MODEL_DESCRIPTION",
                            "subagent_type": "evidence-reviewer"}}])
                return AIMessage(content="观察：合成；推断：未知。")
            if scenario not in {"normal", "state"} and not any(
                    isinstance(m, ToolMessage) for m in messages):
                return AIMessage(content="", tool_calls=[{
                    "name": scenario, "id": "forged-review-tool", "args": {
                        "file_path": "/sentinel.txt", "content": "tampered",
                        "namespace": "kube-triage-demo", "name": "a"}}])
            return AIMessage(content='{"verdict":"UNKNOWN"}')

    class Inspect(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            observed.append(("reviewer", [t.name for t in request.tools],
                             deepcopy(request.state)))
            return await handler(request)

    class Parent(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            filtered = [t for t in request.tools if t.name in MODEL_TOOLS | {"task"}]
            observed.append(("parent", [t.name for t in filtered], {}))
            return await handler(request.override(tools=filtered))

        async def awrap_tool_call(self, request, handler):
            # Native ToolCallRequest override must reach ToolRuntime, retain ID,
            # and leave the original AIMessage unchanged.
            assert request.tool_call["id"] == "native-task-1"
            changed = {**request.tool_call, "args": {
                "description": "HOST_BOUND_DESCRIPTION", "subagent_type": "evidence-reviewer"}}
            result = await handler(request.override(tool_call=changed))
            assert isinstance(result, Command)
            assert set(result.update) == {"messages"}, result.update
            reply = result.update["messages"][0]
            assert isinstance(reply, ToolMessage) and reply.tool_call_id == "native-task-1"
            return result

    parent, reviewer = Fake(role="parent"), Fake(role="reviewer")
    register_harness_profile("protocol_fake", HarnessProfile(
        excluded_tools=baseline._HIDDEN - {"task"},
        excluded_middleware=frozenset({"SummarizationMiddleware"}),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ))
    import deepagents.graph as sdk_graph

    original = sdk_graph.create_agent

    def capture(*args, **kwargs):
        assembled.extend(kwargs["middleware"])
        return original(*args, **kwargs)

    saver = MemorySaver()
    with patch.object(sdk_graph, "create_agent", capture):
        graph = create_deep_agent(
            model=parent, tools=baseline._reader_tools(), backend=StateBackend(),
            middleware=[TodoListMiddleware(), Parent()],
            subagents=[{"name": "evidence-reviewer", "description": "合成审查",
                        "system_prompt": "仅合成审查", "tools": [], "model": reviewer,
                        "middleware": [Inspect()]}],
            checkpointer=saver, skills=None, memory=None,
        )
    native = [m for m in assembled if m.name == "SubAgentMiddleware"]
    assert len(native) == 1
    assert native[0].subagent_names == frozenset({"evidence-reviewer"})

    async def run():
        config = {"configurable": {"thread_id": "review-spike-a"}}
        files = {"/sentinel.txt": create_file_data("SYNTHETIC_PARENT_SENTINEL")}
        inputs = {"messages": [HumanMessage(content="SYNTHETIC_PARENT_MESSAGE")]}
        if scenario == "state":
            inputs["files"] = files
        result = await graph.ainvoke(inputs, config)
        assert all(set(names) == MODEL_TOOLS | {"task"}
                   for role, names, _ in observed if role == "parent")
        # create_agent does not call bind_tools at all when the final list is empty.
        assert all(names == [] for names in reviewer.tools_seen), reviewer.tools_seen
        assert reviewer.inputs
        assert [m.content for m in reviewer.inputs[0] if isinstance(m, HumanMessage)] == [
            "HOST_BOUND_DESCRIPTION"]
        assert "SYNTHETIC_PARENT_SENTINEL" not in str(reviewer.inputs)
        if scenario == "state":
            assert any(state.get("files") == files for role, _, state in observed
                       if role == "reviewer")  # isolated still propagates ordinary State
            assert result["files"] == files
        if scenario not in {"normal", "state"}:
            errors = [m for m in reviewer.inputs[-1] if isinstance(m, ToolMessage)]
            assert len(errors) == 1 and errors[0].status == "error"
        assert not (await graph.aget_state({"configurable": {
            "thread_id": "review-spike-b"}})).values

    asyncio.run(run())
    return {"scenario": scenario, "sdk": version("deepagents")}


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1])))
