"""离线 Backend Spike；characterization 通过不解除 BLOCKED，不注册 B2 Graph。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from threading import Lock

import pytest

SCENARIOS = ["valid", "invalid", "limits", "parallel", "duplicate", "exception", "cancel",
             "update_state", "input_state", "sync", "backend_bypass", "same_thread_runs",
             "file_limit", "total_limit", "parallel_default", "parallel_conflict",
             "cancel_before", "exception_before", "aegra_update_state"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_backend_spike(scenario):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "OTEL_"))}
    env.update(LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", TRIAGE_ENV="test")
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), scenario],
                            env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["scenario"] == scenario


def probe(scenario):
    def forbidden(*args, **kwargs):
        raise AssertionError("Spike 禁止网络与 Reader")

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
    from deepagents.backends.protocol import (
        DeleteResult,
        EditResult,
        FileUploadResponse,
        WriteResult,
    )
    from deepagents.backends.utils import create_file_data
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import MemorySaver
    from pydantic import Field

    from kube_triage import deep_diagnosis as baseline
    from kube_triage.deep_diagnosis_fake import ProtocolFakeModel

    baseline.call_tool = forbidden
    allowed = {f"/scratch/note-{n:02}.md" for n in range(1, 7)}
    scope = ContextVar("spike_scope", default=None)
    observations = {"delegated": 0, "denied": 0, "reads": []}

    class ValidatedStateBackend(StateBackend):
        """测试专用候选，非安全实现。无私有 SDK Send/read/prepare 覆写。

        公共 Backend 写 API 委托；ToolCallRequest 通过边界 ContextVar 提供。
        共享锁刻意保留，以验证锁不能刷新不同 Tool task 的 State 快照。
        """

        def __init__(self):
            self.lock = Lock()
            self.max_files, self.max_total, self.max_writes = 6, 24 * 1024, 3

        def write(self, file_path, content):
            with self.lock:
                ctx = scope.get()
                if ctx is None:
                    observations["denied"] += 1
                    return WriteResult(error="missing trusted tool scope")
                state, ident, raw_path = ctx
                files = state.get("files", {})
                writes = [m for m in state["messages"] if isinstance(m, ToolMessage)
                          and m.name == "write_file" and m.status == "success"]
                try:
                    size = len(content.encode("utf-8"))
                    total = sum(len(f["content"].encode("utf-8")) for f in files.values())
                except (UnicodeError, KeyError, TypeError, AttributeError):
                    return WriteResult(error="invalid encoding/state")
                if (file_path not in allowed or raw_path != file_path or not ident
                        or size > 4096 or "SYNTHETIC_SECRET_SENTINEL" in content
                        or "\x00" in content or file_path in files
                        or len(files) >= self.max_files or total + size > self.max_total
                        or len(writes) >= self.max_writes
                        or any(m.tool_call_id == ident for m in writes)):
                    observations["denied"] += 1
                    return WriteResult(error="prevalidation denied")
                observations["delegated"] += 1
                return super().write(file_path, content)

        def edit(self, *args, **kwargs):
            return EditResult(error="disabled")

        def delete(self, file_path):
            return DeleteResult(error="disabled")

        def upload_files(self, files):
            return [FileUploadResponse(path=p, error="permission_denied") for p, _ in files]

    backend = ValidatedStateBackend()
    cancel_ready = asyncio.Event()
    barrier = asyncio.Barrier(4 if scenario == "parallel_default" else 2)
    script = []

    def call(path="/scratch/note-01.md", content="合成笔记", ident="write-1"):
        return {"name": "write_file", "id": ident,
                "args": {"file_path": path, "content": content}}

    class Fake(ProtocolFakeModel):
        replies: list = Field(default_factory=list)
        seen_tools: list = Field(default_factory=list)

        def bind_tools(self, tools, **kwargs):
            self.seen_tools[:] = sorted(t.name for t in tools)
            return self

        def _reply(self, messages):
            if self.replies:
                return AIMessage(content="", tool_calls=self.replies.pop(0))
            if scenario == "exception" and any(isinstance(m, ToolMessage) for m in messages):
                raise RuntimeError("synthetic failure after accepted tool step")
            return AIMessage(content="合成测试结束，未验证真实集群。")

    class ScopeBoundary(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            tool = request.tool_call
            if tool["name"] not in {"read_file", "write_file"} or (
                tool["args"]["file_path"] not in allowed or not tool["id"]
            ):
                return ToolMessage(content="boundary denied", name=tool["name"],
                                   tool_call_id=tool["id"], status="error")
            token = scope.set((deepcopy(request.runtime.state), tool["id"], tool["args"]["file_path"]))
            try:
                return handler(request)
            finally:
                scope.reset(token)

        def wrap_model_call(self, request, handler):
            return handler(request)

        async def awrap_model_call(self, request, handler):
            if scenario == "cancel" and any(
                isinstance(m, ToolMessage) for m in request.state["messages"]
            ):
                cancel_ready.set()
                await asyncio.Event().wait()
            return await handler(request)

        async def awrap_tool_call(self, request, handler):
            tool = request.tool_call
            # SDK normalizes relative/double-slash paths BEFORE backend.write.
            if tool["name"] not in {"read_file", "write_file"} or (
                tool["args"]["file_path"] not in allowed or not tool["id"]
            ):
                return ToolMessage(content="boundary denied", name=tool["name"],
                                   tool_call_id=tool["id"], status="error")
            if scenario == "exception_before":
                raise RuntimeError("synthetic failure before SDK")
            if scenario == "cancel_before":
                cancel_ready.set()
                await asyncio.Event().wait()
            token = scope.set((deepcopy(request.runtime.state), tool["id"], tool["args"]["file_path"]))
            try:
                if scenario in {"parallel", "duplicate", "parallel_default"}:
                    await asyncio.wait_for(barrier.wait(), timeout=10)
                result = await handler(request)
                if tool["name"] == "read_file":
                    observations["reads"].append(result.content)
                return result
            finally:
                scope.reset(token)

    register_harness_profile("protocol_fake", HarnessProfile(
        excluded_tools=baseline._HIDDEN - {"read_file", "write_file"},
        excluded_middleware=frozenset({"SummarizationMiddleware"}),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ))

    def build(replies, saver):
        model = Fake(replies=deepcopy(replies))
        graph = create_deep_agent(
            model=model, tools=baseline._reader_tools(), backend=backend,
            middleware=[FilesystemMiddleware(
                backend=backend, tools=["read_file", "write_file"],
                tool_token_limit_before_evict=None, human_message_token_limit_before_evict=None,
            ), TodoListMiddleware(), ScopeBoundary()],
            subagents=[], skills=None, memory=None, checkpointer=saver,
        )
        return graph, model

    async def run():
        config = {"configurable": {"thread_id": "synthetic-spike-a"}, "recursion_limit": 100}
        other_config = {"configurable": {"thread_id": "synthetic-spike-b"}}
        saver = MemorySaver()
        if scenario == "valid":
            script.extend([[call()], [{"name": "read_file", "id": "read-1",
                                       "args": {"file_path": "/scratch/note-01.md"}}]])
        elif scenario == "invalid":
            for path in ["/etc/passwd", "/memories/a", "/artifacts/a", "scratch/note-01.md",
                         "/scratch//note-01.md", "/scratch/../note-01.md", "~/a",
                         "https://example.invalid/a", "/scratch/note-%30%31.md",
                         "/scratch/nоte-01.md", "/scratch/note-01.md\x00"]:
                script.append([call(path=path, ident=f"invalid-{len(script)}")])
            for content in ["x" * 4097, "中" * 1366, "SYNTHETIC_SECRET_SENTINEL", "a\x00b"]:
                script.append([call(content=content, ident=f"invalid-{len(script)}")])
        elif scenario == "limits":
            script.extend([[call(f"/scratch/note-{i:02}.md", "x" * 4096, f"write-{i}")]
                           for i in range(1, 5)])
            script.append([call(content="overwrite", ident="overwrite")])
        elif scenario in {"file_limit", "total_limit"}:
            if scenario == "file_limit":
                backend.max_files = 1
            else:
                backend.max_total = 4096
            script.extend([[call(content="x" * 4096)],
                           [call("/scratch/note-02.md", "y" * 4096, "write-2")]])
        elif scenario == "parallel_default":
            script.append([call(f"/scratch/note-{i:02}.md", "x", f"write-{i}")
                           for i in range(1, 5)])
        elif scenario == "parallel_conflict":
            script.append([call(), call(content="conflicting synthetic note", ident="write-2")])
        elif scenario == "parallel":
            # Lower injectable ceilings to reach aggregate constraints independently.
            backend.max_files, backend.max_total, backend.max_writes = 1, 4096, 1
            script.append([call(content="x" * 4096),
                           call("/scratch/note-02.md", "y" * 4096, "write-2")])
        elif scenario == "duplicate":
            backend.max_writes = 1
            script.append([call(ident="same-id"), call("/scratch/note-02.md", ident="same-id")])
        elif scenario in {"exception", "cancel", "sync", "exception_before", "cancel_before"}:
            script.append([call()])
        graph, model = build(script, saver)
        if scenario in {"update_state", "input_state", "backend_bypass", "same_thread_runs", "aegra_update_state"}:
            await graph.ainvoke({"messages": [HumanMessage(content="合成空基线")]}, config)
            before = await graph.aget_state(config)
            foreign = {"/etc/forged.md": create_file_data("SYNTHETIC_SECRET_SENTINEL")}
            if scenario == "aegra_update_state":
                # Real installed endpoint function + real graph/MemorySaver;
                # only ownership DB lookup and graph acquisition are synthetic.
                from contextlib import asynccontextmanager
                from types import SimpleNamespace
                from unittest.mock import AsyncMock, patch

                from aegra_api.api.threads import update_thread_state
                from aegra_api.models import ThreadStateUpdate, User

                @asynccontextmanager
                async def get_graph(*args, **kwargs):
                    assert kwargs["access_context"] == "threads.update"
                    yield graph

                service = SimpleNamespace(get_graph=get_graph)
                session = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(
                    metadata_json={"graph_id": "synthetic-spike-only"})))
                with patch("aegra_api.services.langgraph_service.get_langgraph_service",
                           return_value=service):
                    response = await update_thread_state(
                        config["configurable"]["thread_id"],
                        ThreadStateUpdate(values={"files": foreign}),
                        User(identity="synthetic-spike-user"), session)
                assert response.checkpoint["checkpoint_id"]
                assert (await graph.aget_state(config)).values["files"] == foreign
                assert observations["delegated"] == 0
            elif scenario == "update_state":
                updated = await graph.aupdate_state(config, {"files": foreign})
                assert (await graph.aget_state(updated)).values["files"] == foreign
                assert observations["delegated"] == 0
                assert (await graph.aget_state(before.config)).values.get("files", {}) == {}
                rebuilt, _ = build([], saver)
                assert (await rebuilt.aget_state(config)).values["files"] == foreign
            elif scenario == "input_state":
                state = await graph.ainvoke({"messages": [HumanMessage(content="合成注入")],
                                            "files": foreign}, config)
                assert state["files"] == foreign
                assert observations["delegated"] == 0
            elif scenario == "backend_bypass":
                assert backend.edit("/x", "a", "b").error
                assert backend.delete("/x").error
                assert all(r.error for r in backend.upload_files([("/x", b"x")]))
                assert (await backend.aedit("/x", "a", "b")).error
                assert (await backend.adelete("/x")).error
                assert all(r.error for r in await backend.aupload_files([("/x", b"x")]))
                assert backend.write("/scratch/note-01.md", "no tool scope").error
            else:
                # Separate graph instances sharing a saver and pinned checkpoint;
                # no cross-run reservation is provided by this Backend API.
                backend.max_files, backend.max_total, backend.max_writes = 1, 4096, 1
                a, _ = build([[call(content="x" * 4096)]], saver)
                b, _ = build([[call("/scratch/note-02.md", "y" * 4096, "write-2")]], saver)
                results = await asyncio.gather(*[
                    g.ainvoke({"messages": [HumanMessage(content="并发合成 Run")]}, before.config)
                    for g in (a, b)
                ])
                assert observations["delegated"] == 2
                assert all(len(r["files"]) == 1 for r in results)
                histories = [s async for s in graph.aget_state_history(config)]
                assert any("/scratch/note-01.md" in s.values.get("files", {}) for s in histories)
                assert any("/scratch/note-02.md" in s.values.get("files", {}) for s in histories)
            return
        if scenario == "sync":
            state = await asyncio.to_thread(graph.invoke,
                                            {"messages": [HumanMessage(content="同步合成")]}, config)
            assert observations["delegated"] == 1
            assert state["files"]["/scratch/note-01.md"]["content"] == "合成笔记"
            assert (await graph.aget_state(config)).values["files"] == state["files"]
            return
        try:
            if scenario in {"cancel", "cancel_before"}:
                task = asyncio.create_task(graph.ainvoke(
                    {"messages": [HumanMessage(content="合成取消探针")]}, config))
                await asyncio.wait_for(cancel_ready.wait(), timeout=10)
                task.cancel()
                await task
                raise AssertionError("cancellation must propagate")
            state = await graph.ainvoke({"messages": [HumanMessage(content="合成探针")]}, config)
        except (RuntimeError, asyncio.CancelledError) as exc:
            assert str(exc).startswith("synthetic failure") or isinstance(exc, asyncio.CancelledError)
            observations["termination"] = type(exc).__name__
            assert scenario in {"exception", "cancel", "exception_before", "cancel_before"}
            state = (await graph.aget_state(config)).values
        assert model.seen_tools == sorted({
            "pods_list_in_namespace", "pods_get", "events_list", "pods_log", "write_todos",
            "read_file", "write_file",
        })
        assert (await graph.aget_state(config)).values.get("files", {}) == state.get("files", {})
        histories = [s async for s in graph.aget_state_history(config)]
        checkpoints = [c async for c in saver.alist(config)]
        if scenario in {"invalid", "exception_before", "cancel_before"}:
            assert observations["delegated"] == 0
            assert all(not s.values.get("files") for s in histories)
            assert all(channel != "files" for c in checkpoints
                       for _, channel, _ in c.pending_writes)
            replies = [m for m in state["messages"] if isinstance(m, ToolMessage)]
            assert len(replies) == (len(script) if scenario == "invalid" else 0)
            assert all(m.status == "error" for m in replies)
            if scenario == "invalid":
                assert [m.tool_call_id for m in replies] == [c[0]["id"] for c in script]
        elif scenario in {"file_limit", "total_limit"}:
            assert observations["delegated"] == 1
            assert len(state["files"]) == 1
            replies = [m for m in state["messages"] if isinstance(m, ToolMessage)]
            assert [m.status for m in replies] == ["success", "error"]
        elif scenario == "parallel_default":
            assert observations["delegated"] == 4
            assert len(state["files"]) == 4 > backend.max_writes
        elif scenario == "parallel_conflict":
            # Native middleware rejects the second mutation of one path in a batch.
            assert observations["delegated"] == 1
            assert len(state["files"]) == 1
            replies = [m for m in state["messages"] if isinstance(m, ToolMessage)]
            assert [m.status for m in replies] == ["success", "error"]
        elif scenario == "limits":
            assert observations["delegated"] == 3
            assert len(state["files"]) == 3
            assert state["files"]["/scratch/note-01.md"]["content"] == "x" * 4096
            replies = [m for m in state["messages"] if isinstance(m, ToolMessage)]
            assert [m.status for m in replies] == ["success"] * 3 + ["error"] * 2
        elif scenario in {"parallel", "duplicate"}:
            # Known blocker: both calls observe pre-superstep State despite shared lock.
            assert observations["delegated"] == 2
            assert len(state["files"]) == 2
            assert len(state["files"]) > backend.max_writes
        else:
            assert observations["delegated"] == 1
            assert state["files"]["/scratch/note-01.md"]["content"] == "合成笔记"
        other, _ = build([], saver)
        # Execute another Thread rather than only inspecting an absent Thread.
        isolated = await other.ainvoke({"messages": [HumanMessage(content="第二合成 Thread")]},
                                      other_config)
        assert isolated.get("files", {}) == {}
        if scenario == "valid":
            assert any("合成笔记" in text for text in observations["reads"])
            rebuilt, _ = build([[{"name": "read_file", "id": "read-rebuilt",
                                 "args": {"file_path": "/scratch/note-01.md"}}]], saver)
            await rebuilt.ainvoke({"messages": [HumanMessage(content="同 Thread 合成重建读取")]},
                                 config)
            assert "合成笔记" in observations["reads"][-1]
        observations["files"] = sorted(state.get("files", {}))

    asyncio.run(run())
    return {"scenario": scenario, **observations}


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1]), ensure_ascii=False))
