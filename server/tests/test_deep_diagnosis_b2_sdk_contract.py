"""B2-A SDK 契约调查；characterization 通过不代表 B2-A 安全 Gate 通过。

每个探针使用新解释器隔离 SDK Profile registry；仅合成数据、内存 Checkpoint，
禁止网络。这里没有可加载的 B2 Graph，不构成 B2-A 实施完成。
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["accept", "reject_before", "reject_after", "profile_collision"])
def test_locked_sdk_contract(scenario):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "OTEL_"))}
    env.update(LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", TRIAGE_ENV="test")
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), scenario],
        env=env, capture_output=True, text=True, timeout=45, check=True,
    )
    result = json.loads(completed.stdout)
    expected = {"pods_list_in_namespace", "pods_get", "events_list", "pods_log", "write_todos"}
    if scenario == "profile_collision":
        # A/B1's exclusion sets union into B2 when built in the same interpreter.
        assert result["tools"] == sorted(expected)
        assert result["files"] == {}
        return
    assert result["tools"] == sorted(expected | {"read_file", "write_file"})
    assert result["other_thread_files"] == {}
    assert result["checkpoint_files"] == result["files"]
    if scenario == "reject_before":
        assert result["handler_called"] is False
        assert result["files"] == {}
        assert result["replies"] == [["probe-write", "error"]]
    elif scenario == "reject_after":
        assert result["sdk_return_type"] == "ToolMessage"
        assert result["sdk_status"] == "success"
        assert result["replies"] == [["probe-write", "error"]]
        # Known blocker: rejecting the receipt does NOT roll back StateBackend's send.
        assert result["files"]["/scratch/note-01.md"]["content"] == "synthetic note"
    else:
        assert result["files"]["/scratch/note-01.md"]["content"] == "synthetic note"
        assert result["replies"] == [["probe-write", "success"], ["probe-read", "success"]]
        assert "synthetic note" in result["read_content"]


def _probe(scenario):
    """仅子进程入口；禁止在 pytest 主进程中修改网络或 Profile。"""
    def forbidden(*args, **kwargs):
        raise AssertionError("B2 SDK contract probe forbids Reader/network access")

    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden
    socket.create_connection = forbidden

    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        create_deep_agent,
        register_harness_profile,
    )
    from deepagents.backends import StateBackend
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import MemorySaver
    from pydantic import Field

    from kube_triage import deep_diagnosis as baseline
    from kube_triage.deep_diagnosis_fake import ProtocolFakeModel

    baseline.call_tool = forbidden
    observed = {"handler_called": False}

    class Fake(ProtocolFakeModel):
        seen_tools: list[str] = Field(default_factory=list)

        def bind_tools(self, tools, **kwargs):
            self.seen_tools[:] = sorted(tool.name for tool in tools)
            return self

        def _reply(self, messages):
            replies = [m for m in messages if isinstance(m, ToolMessage)]
            if scenario == "profile_collision" or replies and scenario != "accept":
                return AIMessage(content="合成契约调查结束；真实状态未核验。")
            if not replies:
                return AIMessage(content="", tool_calls=[{
                    "name": "write_file", "id": "probe-write", "args": {
                        "file_path": "/scratch/note-01.md", "content": "synthetic note",
                    },
                }])
            if len(replies) == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "read_file", "id": "probe-read",
                    "args": {"file_path": "/scratch/note-01.md"},
                }])
            return AIMessage(content="仅验证合成笔记；真实状态未核验。")

    class ProbeBoundary(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            def rejected():
                return ToolMessage(content="合成验证拒绝", name=request.tool_call["name"],
                                   tool_call_id=request.tool_call["id"], status="error")

            if scenario == "reject_before":
                return rejected()
            observed["handler_called"] = True
            result = await handler(request)
            observed.update(sdk_return_type=type(result).__name__, sdk_status=result.status)
            return rejected() if scenario == "reject_after" else result

    async def run():
        if scenario == "profile_collision":
            # Reproduce existing registrations, without invoking either graph/model.
            from kube_triage import deep_diagnosis_planning as planning

            baseline.build_graph(Fake())
            planning.build_graph(Fake())
        register_harness_profile("protocol_fake", HarnessProfile(
            excluded_tools=baseline._HIDDEN - {"read_file", "write_file"},
            excluded_middleware=frozenset({"SummarizationMiddleware"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ))
        backend = StateBackend()
        model = Fake()
        graph = create_deep_agent(
            model=model, tools=baseline._reader_tools(), backend=backend,
            middleware=[FilesystemMiddleware(
                backend=backend, tools=["read_file", "write_file"],
                tool_token_limit_before_evict=None, human_message_token_limit_before_evict=None,
            ), TodoListMiddleware(), ProbeBoundary()],
            subagents=[], skills=None, memory=None, checkpointer=MemorySaver(),
        )
        config = {"configurable": {"thread_id": "synthetic-b2-contract"}}
        state = await graph.ainvoke({"messages": [HumanMessage(content="合成契约调查")]}, config)
        saved = await graph.aget_state(config)
        other = await graph.aget_state({"configurable": {"thread_id": "synthetic-b2-other"}})
        replies = [m for m in state["messages"] if isinstance(m, ToolMessage)]
        return {**observed, "tools": model.seen_tools, "files": state.get("files", {}),
                "checkpoint_files": saved.values.get("files", {}),
                "other_thread_files": other.values.get("files", {}),
                "replies": [[m.tool_call_id, m.status] for m in replies],
                "read_content": next((m.content for m in replies if m.name == "read_file"), "")}

    return asyncio.run(run())


if __name__ == "__main__":
    print(json.dumps(_probe(sys.argv[1]), ensure_ascii=False))
